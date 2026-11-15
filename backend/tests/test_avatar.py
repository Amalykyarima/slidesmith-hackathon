"""Live avatar: room tokens dispatch the worker with the right metadata; the worker signs in by secret."""
import json

import jwt as _jwt  # noqa: F401  (pyjwt comes with livekit-api)
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(config, "LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setattr(config, "LIVEKIT_API_KEY", "APIkey")
    monkeypatch.setattr(config, "LIVEKIT_API_SECRET", "s" * 40)
    monkeypatch.setattr(config, "AVATAR_SECRET", "avatar-secret")
    monkeypatch.setattr(config, "AVATAR_ENABLED", True)


def _claims(token: str) -> dict:
    import jwt
    return jwt.decode(token, options={"verify_signature": False})


def test_avatar_off_without_keys(monkeypatch):
    monkeypatch.setattr(config, "AVATAR_ENABLED", False)
    with TestClient(app) as c:
        assert c.get("/api/avatar").json() == {"configured": False}
        assert c.post("/api/avatar/token", json={"mode": "build"}).status_code == 503


def test_build_token_dispatches_worker(live):
    with TestClient(app) as c:
        r = c.post("/api/avatar/token", json={"mode": "build", "level": "primary"})
        assert r.status_code == 200, r.text
        body = r.json()
        claims = _claims(body["token"])
        agents = claims["roomConfig"]["agents"]
        assert agents[0]["agentName"] == "slidesmith-avatar"
        meta = json.loads(agents[0]["metadata"])
        assert meta == {"mode": "build", "owner": "", "level": "primary"}
        assert claims["video"]["room"] == body["room"]
        debrief = c.post("/api/avatar/token", json={"mode": "debrief"}).json()
        meta2 = json.loads(_claims(debrief["token"])["roomConfig"]["agents"][0]["metadata"])
        assert meta2["mode"] == "debrief"
        # Presenting needs a deck the teacher owns.
        assert c.post("/api/avatar/token", json={"mode": "present", "generation_id": "nope"}).status_code == 404


def test_worker_signs_in_as_teacher(live, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_CODES", {"maple-42": "Mrs Khan"})
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    with TestClient(app) as c:
        assert c.get("/api/styles").status_code == 401
        assert c.get("/api/styles", headers={"X-Avatar-Secret": "wrong", "X-Owner": "Mrs Khan"}).status_code == 401
        assert c.get("/api/styles", headers={"X-Avatar-Secret": "avatar-secret"}).status_code == 401  # no owner
        ok = c.get("/api/session", headers={"X-Avatar-Secret": "avatar-secret", "X-Owner": "Mrs Khan"})
        assert ok.json()["name"] == "Mrs Khan"


def test_pupil_token_carries_pupil(live):
    with TestClient(app) as c:
        pupils = c.post("/api/sen/demo").json()
        ab = next(p for p in pupils if p["code"] == "Y4-AB")
        body = c.post("/api/avatar/token", json={"mode": "pupil", "pupil_id": ab["id"]}).json()
        meta = json.loads(_claims(body["token"])["roomConfig"]["agents"][0]["metadata"])
        assert meta["mode"] == "pupil" and meta["pupil_id"] == ab["id"]
        assert c.post("/api/avatar/token", json={"mode": "pupil", "pupil_id": "nope"}).status_code == 404
