"""SEN copilot in demo mode: guardrails on pupil identity, APDR records, drafts, sign-off, dashboard, RAG."""
import io

from fastapi.testclient import TestClient

from app import kb
from app.main import app


def _clean(c):
    for p in c.get("/api/sen/pupils").json():
        c.delete(f"/api/sen/pupils/{p['id']}")
    for d in c.get("/api/sen/docs").json():
        c.delete(f"/api/sen/docs/{d['id']}")


def test_pupils_refuse_names():
    with TestClient(app) as c:
        _clean(c)
        assert c.post("/api/sen/pupils", json={"code": "Amelia Jones"}).status_code == 400
        assert c.post("/api/sen/pupils", json={"code": "a@b.com"}).status_code == 400
        r = c.post("/api/sen/pupils", json={"code": "Y4-AB", "needs": ["autism"], "summary": "Call mum on 07700 900123"})
        assert r.status_code == 201 and r.json()["need_area"] == "communication_interaction"
        assert "07700" not in r.json()["summary"]
        assert c.post("/api/sen/pupils", json={"code": "Y4-AB"}).status_code == 409
        _clean(c)


def test_demo_dashboard_records_drafts():
    with TestClient(app) as c:
        _clean(c)
        dash = c.post("/api/sen/demo").json()
        assert dash["counts"]["pupils"] == 5 and dash["counts"]["overdue"] == 1
        assert dash["counts"]["attendance_flags"] >= 2
        gh = next(p for p in dash["pupils"] if p["code"] == "Y5-GH")
        assert gh["attendance"]["flag"] == "persistent"
        assert c.post("/api/sen/demo").json()["counts"]["pupils"] == 5  # idempotent

        ab = next(p for p in dash["pupils"] if p["code"] == "Y4-AB")
        note = c.get("/api/sen/demo/note").json()["note"]
        rec = c.post(f"/api/sen/pupils/{ab['id']}/records", json={"note": note}).json()
        assert rec["status"] == "draft" and rec["record"]["plan"]["outcomes"] and rec["review_date"]
        assert c.post(f"/api/sen/records/{rec['id']}/approve", json={}).status_code == 400  # needs a name
        ok = c.post(f"/api/sen/records/{rec['id']}/approve", json={"approved_by": "Ms Patel (SENCO)"}).json()
        assert ok["status"] == "approved"
        assert c.get(f"/api/sen/pupils/{ab['id']}").json()["next_review"] == rec["review_date"]

        d = c.post(f"/api/sen/pupils/{ab['id']}/drafts", json={"kind": "support_plan"}).json()
        assert d["status"] == "draft"
        assert c.post(f"/api/sen/drafts/{d['id']}/sign", json={"signed_by": "Ms Patel"}).status_code == 400  # [to add:]
        signed = c.post(f"/api/sen/drafts/{d['id']}/sign", json={"signed_by": "Ms Patel", "body": "## Plan\nAgreed."}).json()
        assert signed["status"] == "signed"
        assert c.patch(f"/api/sen/drafts/{d['id']}", json={"body": "x"}).status_code == 409

        a = c.post("/api/sen/adapt", json={"work": "Fractions worksheet\nShade half of each shape\nWrite the fraction",
                                           "needs": ["mld"]}).json()
        assert a["draft"] and a["tasks"]
        csv = b"code,attendance,recent\nY4-CD,89.0,85\n"
        assert c.post("/api/sen/attendance", files={"file": ("a.csv", io.BytesIO(csv))}).json() == {"rows": 1}
        _clean(c)


def test_kb_search_prefers_school_docs():
    with TestClient(app) as c:
        _clean(c)
        c.post("/api/sen/demo")
        hits = c.get("/api/sen/search", params={"q": "speech language group"}).json()
        assert hits[0]["id"].startswith("S") and "Language Link" in hits[0]["text"]
        assert any(h["id"].startswith("C") for h in c.get("/api/sen/search", params={"q": "assess plan do review"}).json())
        assert kb.cited("as shown [C3] and [S1]", hits + kb.passages("")[:5])
        _clean(c)
