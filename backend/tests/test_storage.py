"""Saving work to Supabase Storage so it survives the server's disk being wiped.

A small fake Supabase server checks the exact HTTP calls (paths, keys, upsert)."""
import io
import json
import shutil
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation

from app import config, storage
from app.main import app

FIX = Path(__file__).parent / "fixtures"
KEY = "service-key-123"


class FakeSupabase:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[str] = []
        store = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _ok_auth(self):
                if self.headers.get("Authorization") != f"Bearer {KEY}" or self.headers.get("apikey") != KEY:
                    self.send_response(401)
                    self.end_headers()
                    return False
                return True

            def _body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _reply(self, code, data=b"{}"):
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                store.calls.append(f"GET {self.path}")
                if not self._ok_auth():
                    return
                prefix = "/storage/v1/object/authenticated/bucket-x/"
                key = unquote(self.path[len(prefix):]) if self.path.startswith(prefix) else None
                if key in store.objects:
                    self._reply(200, store.objects[key])
                else:
                    self._reply(400, b'{"error":"not_found","message":"Object not found"}')

            def do_POST(self):
                store.calls.append(f"POST {self.path}")
                if not self._ok_auth():
                    return
                body = self._body()
                if self.path == "/storage/v1/object/list/bucket-x":
                    return self._reply(200, b"[]")
                prefix = "/storage/v1/object/bucket-x/"
                assert self.path.startswith(prefix) and self.headers.get("x-upsert") == "true"
                store.objects[unquote(self.path[len(prefix):])] = body
                self._reply(200)

            def do_DELETE(self):
                store.calls.append(f"DELETE {self.path}")
                if not self._ok_auth():
                    return
                assert self.path == "/storage/v1/object/bucket-x"
                for key in json.loads(self._body())["prefixes"]:
                    store.objects.pop(key, None)
                self._reply(200, b"[]")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def bucket(self):
        return storage.SupabaseBucket(self.url, KEY, "bucket-x")


@pytest.fixture
def supabase():
    fake = FakeSupabase()
    yield fake
    fake.server.shutdown()


def _make_db(path: Path, rows: list[str]) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS t (name TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    con.commit()
    con.close()


def test_save_and_restore_round_trip(supabase, tmp_path):
    a = tmp_path / "server-a"
    (a / "styles").mkdir(parents=True)
    (a / "styles" / "s1.pptx").write_bytes(b"deck" * 100)
    (a / "previews" / "generations" / "g1").mkdir(parents=True)
    (a / "previews" / "generations" / "g1" / "1.jpg").write_bytes(b"jpg")
    (a / "outputs").mkdir()
    (a / "outputs" / "g1.editing.pptx").write_bytes(b"half-saved")  # temporary: never stored
    _make_db(a / "slidesmith.db", ["Mrs Khan's style"])

    sync = storage.Sync(supabase.bucket(), a, a / "slidesmith.db")
    assert sync.sync_once() == 3  # 2 files + the database (the half-saved file is skipped)
    assert set(supabase.objects) == {"styles/s1.pptx", "previews/generations/g1/1.jpg", "slidesmith.db", "manifest.json"}
    assert sync.sync_once() == 0  # nothing changed: nothing uploaded

    # The disk is wiped (Render sleep). A new server brings everything back.
    b = tmp_path / "server-b"
    b.mkdir()
    fresh = storage.Sync(supabase.bucket(), b, b / "slidesmith.db")
    assert fresh.restore() == 2
    assert (b / "styles" / "s1.pptx").read_bytes() == b"deck" * 100
    assert (b / "previews" / "generations" / "g1" / "1.jpg").read_bytes() == b"jpg"
    con = sqlite3.connect(b / "slidesmith.db")
    assert con.execute("SELECT name FROM t").fetchall() == [("Mrs Khan's style",)]
    con.close()
    assert fresh.sync_once() == 0  # restored files are not uploaded again

    # A deleted style is deleted from the bucket too; a database change is saved.
    (b / "styles" / "s1.pptx").unlink()
    _make_db(b / "slidesmith.db", ["another"])
    assert fresh.sync_once() >= 2
    assert "styles/s1.pptx" not in supabase.objects
    assert sorted(json.loads(supabase.objects["manifest.json"])) == ["previews/generations/g1/1.jpg"]


def test_empty_bucket_and_wrong_key(supabase, tmp_path):
    sync = storage.Sync(supabase.bucket(), tmp_path, tmp_path / "x.db")
    assert sync.restore() == 0  # nothing saved yet is fine
    bad = storage.Sync(storage.SupabaseBucket(supabase.url, "wrong", "bucket-x"), tmp_path, tmp_path / "x.db")
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(Exception):
        bad.sync_once()


def test_app_keeps_work_after_the_disk_is_wiped(supabase, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", supabase.url)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", KEY)
    monkeypatch.setenv("SUPABASE_BUCKET", "bucket-x")
    monkeypatch.setenv("SYNC_INTERVAL", "3600")  # only the shutdown save, to keep the test exact
    with TestClient(app) as c:
        assert c.get("/api/health").json()["storage"]["mode"] == "supabase"
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        gen = c.post("/api/build", json={"style_id": style["id"], "title": "Kept",
                                         "slides": [{"page": 1, "title": "Still here"}]}).json()
    # leaving the block = server shutdown: last save
    assert f"styles/{style['id']}.pptx" in supabase.objects and "slidesmith.db" in supabase.objects

    root = config.STORAGE_DIR
    for item in root.iterdir():  # the free server's disk is wiped
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    for d in (config.STYLES_DIR, config.IMAGES_DIR, config.OUTPUTS_DIR, config.PREVIEWS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as c:
        assert style["id"] in [s["id"] for s in c.get("/api/styles").json()]
        deck = c.get(gen["download_url"])
        assert deck.status_code == 200
        slide = Presentation(io.BytesIO(deck.content)).slides[0]
        assert any("Still here" in sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)
    storage._sync = None

