"""Keep teachers' work when the server's disk is wiped (Render free: every sleep/deploy).

The app keeps working on local disk exactly as before. When SUPABASE_URL and
SUPABASE_SERVICE_KEY are set, a background thread copies new or changed files (style
decks, pictures, generated decks, previews) and a snapshot of the database to a private
Supabase Storage bucket every few seconds, and once more on shutdown. On startup, before
anything reads the database, everything is copied back.

A small manifest (manifest.json in the bucket) lists what is stored, so restoring is one
listing call plus one download per file.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from . import config

log = logging.getLogger("slidesmith.storage")

MANIFEST = "manifest.json"
DB_KEY = "slidesmith.db"
MAX_FILE = 50 * 1024 * 1024  # Supabase free plan: 50 MB per file
SKIP_SUFFIXES = (".db", ".db-journal", ".db-wal", ".db-shm", ".editing.pptx", ".tmp")


class SupabaseBucket:
    """The few Supabase Storage calls we need, over plain HTTPS (no extra packages)."""

    def __init__(self, url: str, key: str, bucket: str):
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {key}", "apikey": key}

    def _call(self, method: str, path: str, data=None, headers: dict | None = None, timeout: int = 60) -> bytes:
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={**self.headers, **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (configured https URL)
            return resp.read()

    def _obj(self, key: str) -> str:
        return f"/object/{quote(self.bucket)}/{quote(key)}"

    def get(self, key: str) -> bytes | None:
        try:
            return self._call("GET", f"/object/authenticated/{quote(self.bucket)}/{quote(key)}")
        except urllib.error.HTTPError as err:
            if err.code in (400, 404):  # Supabase answers 400 "Object not found" for missing keys
                return None
            raise

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._call("POST", self._obj(key), data=data,
                   headers={"Content-Type": content_type, "x-upsert": "true", "Cache-Control": "no-cache"},
                   timeout=180)

    def delete(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 100):
            body = json.dumps({"prefixes": keys[i:i + 100]}).encode()
            self._call("DELETE", f"/object/{quote(self.bucket)}", data=body,
                       headers={"Content-Type": "application/json"})

    def ping(self) -> None:
        """A tiny request: keeps a free Supabase project from pausing after a quiet week."""
        self._call("POST", f"/object/list/{quote(self.bucket)}",
                   data=json.dumps({"prefix": "", "limit": 1}).encode(),
                   headers={"Content-Type": "application/json"}, timeout=20)


def _content_type(path: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".json": "application/json",
    }.get(Path(path).suffix.lower(), "application/octet-stream")


class Sync:
    """Mirrors config.STORAGE_DIR to a bucket."""

    def __init__(self, bucket, root: Path, db_path: Path, interval: float = 15):
        self.bucket = bucket
        self.root = root
        self.db_path = db_path
        self.interval = interval
        self.remote: dict[str, list] = {}  # key -> [size, local mtime_ns when uploaded]
        self.db_mtime: int | None = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self.last_ping = 0.0

    # ------------------------------------------------------------------ restore
    def restore(self) -> int:
        """Bring back the database and every stored file. Returns how many files came back."""
        raw = self.bucket.get(MANIFEST)
        if raw is None:
            log.info("Storage: nothing saved yet (new bucket)")
            return 0
        manifest: dict[str, list] = json.loads(raw)
        if not self.db_path.exists():
            data = self.bucket.get(DB_KEY)
            if data:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self.db_path.write_bytes(data)
        if self.db_path.exists():
            self.db_mtime = self.db_path.stat().st_mtime_ns

        def fetch(key: str) -> int:
            local = self.root / key
            if not local.exists():
                data = self.bucket.get(key)
                if data is None:
                    return 0
                local.parent.mkdir(parents=True, exist_ok=True)
                tmp = local.with_name(local.name + ".tmp")
                tmp.write_bytes(data)
                tmp.replace(local)
            st = local.stat()
            self.remote[key] = [st.st_size, st.st_mtime_ns]
            return 1

        with ThreadPoolExecutor(max_workers=6) as pool:
            count = sum(pool.map(fetch, manifest))
        self.last_ok = time.time()
        log.info("Storage: restored the database and %d files", count)
        return count

    # --------------------------------------------------------------------- sync
    def _local_files(self) -> dict[str, list]:
        found: dict[str, list] = {}
        for path in self.root.rglob("*"):
            if not path.is_file() or path.name.endswith(SKIP_SUFFIXES):
                continue
            try:
                st = path.stat()
            except FileNotFoundError:
                continue  # removed while we looked
            found[path.relative_to(self.root).as_posix()] = [st.st_size, st.st_mtime_ns]
        return found

    def _db_snapshot(self) -> bytes:
        """A consistent copy of the database, even while it is being written."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snap.db"
            src = sqlite3.connect(self.db_path, timeout=30)
            dst = sqlite3.connect(out)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            return out.read_bytes()

    def sync_once(self) -> int:
        """Upload what changed, delete what was removed. Returns how many objects changed."""
        with self.lock:
            changed = 0
            local = self._local_files()
            for key, meta in local.items():
                if self.remote.get(key) == meta:
                    continue
                if meta[0] > MAX_FILE:
                    if self.remote.get(key) != meta:
                        log.warning("Storage: %s is over 50 MB, not saved", key)
                        self.remote[key] = meta
                    continue
                path = self.root / key
                try:
                    data = path.read_bytes()
                except FileNotFoundError:
                    continue
                self.bucket.put(key, data, _content_type(key))
                self.remote[key] = meta
                changed += 1
            gone = [k for k in self.remote if k not in local]
            if gone:
                self.bucket.delete(gone)
                for k in gone:
                    self.remote.pop(k, None)
                changed += len(gone)
            if self.db_path.exists():
                mtime = self.db_path.stat().st_mtime_ns
                if mtime != self.db_mtime:
                    self.bucket.put(DB_KEY, self._db_snapshot())
                    self.db_mtime = mtime
                    changed += 1
            if changed:
                self.bucket.put(MANIFEST, json.dumps(self.remote).encode(), "application/json")
            elif time.time() - self.last_ping > 24 * 3600:
                self.bucket.ping()
            self.last_ping = time.time()
            self.last_ok = time.time()
            self.last_error = None
            return changed

    def _loop(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                if n := self.sync_once():
                    log.info("Storage: saved %d changes", n)
            except Exception as err:  # noqa: BLE001 (network hiccup: try again next round)
                self.last_error = str(err)[:200]
                log.warning("Storage sync failed (will retry): %s", err)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="storage-sync", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Last save before the server goes to sleep."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        try:
            self.sync_once()
        except Exception as err:  # noqa: BLE001
            log.warning("Storage: final save failed: %s", err)

    def status(self) -> dict:
        return {
            "mode": "supabase",
            "files": len(self.remote),
            "last_saved_seconds_ago": None if self.last_ok is None else round(time.time() - self.last_ok),
            "error": self.last_error,
        }


_sync: Sync | None = None


def enabled() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_SERVICE_KEY", "").strip())


def startup() -> None:
    """Restore before the database is opened, then keep saving in the background."""
    global _sync
    if not enabled():
        log.info("Storage: local disk only (set SUPABASE_URL and SUPABASE_SERVICE_KEY to keep work across restarts)")
        return
    bucket = SupabaseBucket(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_SERVICE_KEY"].strip(),
                            os.getenv("SUPABASE_BUCKET", "slidesmith").strip() or "slidesmith")
    _sync = Sync(bucket, config.STORAGE_DIR, config.DB_PATH, float(os.getenv("SYNC_INTERVAL", "15")))
    try:
        _sync.restore()
    except Exception as err:  # noqa: BLE001
        # Better to start (and save new work) than to stay down; nothing local is overwritten.
        _sync.last_error = f"restore failed: {err}"[:200]
        log.exception("Storage: restore failed")
    _sync.start()


def shutdown() -> None:
    if _sync:
        _sync.stop()


def status() -> dict:
    return _sync.status() if _sync else {"mode": "local"}
