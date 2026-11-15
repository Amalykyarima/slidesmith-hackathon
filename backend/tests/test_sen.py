"""SEN copilot in demo mode: guardrails on pupil identity, APDR records and approval, adaptation, RAG."""
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


def test_demo_records_and_adapt():
    with TestClient(app) as c:
        _clean(c)
        pupils = c.post("/api/sen/demo").json()
        assert len(pupils) == 5 and len(c.post("/api/sen/demo").json()) == 5  # idempotent
        ab = next(p for p in pupils if p["code"] == "Y4-AB")
        assert ab["records"] == 1
        for gone in ("/api/sen/dashboard", "/api/sen/attendance"):
            assert c.get(gone).status_code in (404, 405)

        note = c.get("/api/sen/demo/note").json()["note"]
        rec = c.post(f"/api/sen/pupils/{ab['id']}/records", json={"note": note}).json()
        assert rec["status"] == "draft" and rec["record"]["plan"]["outcomes"] and rec["review_date"]
        assert c.post(f"/api/sen/records/{rec['id']}/approve", json={}).status_code == 400  # needs a name
        ok = c.post(f"/api/sen/records/{rec['id']}/approve", json={"approved_by": "Ms Patel (SENCO)"}).json()
        assert ok["status"] == "approved"
        detail = c.get(f"/api/sen/pupils/{ab['id']}").json()
        assert detail["next_review"] == rec["review_date"] and len(detail["records"]) == 2

        a = c.post("/api/sen/adapt", json={"work": "Fractions worksheet\nShade half of each shape\nWrite the fraction",
                                           "needs": ["mld"]}).json()
        assert a["draft"] and a["tasks"]
        assert c.get(f"/api/sen/adaptations/{a['id']}").json()["title"] == a["title"]
        assert c.get("/api/sen/adaptations/nope").status_code == 404
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


def test_pupil_day_and_help():
    with TestClient(app) as c:
        _clean(c)
        pupils = c.post("/api/sen/demo").json()
        ab = next(p for p in pupils if p["code"] == "Y4-AB")
        day = c.get(f"/api/sen/pupils/{ab['id']}/day").json()
        assert len(day["periods"]) == 3 and day["periods"][0]["breakdown"]["task_steps"]
        saved = c.put(f"/api/sen/pupils/{ab['id']}/day", json={"periods": [
            {"subject": "PE", "learn": "Throwing and catching\\nWarm up\\nThrow to a partner", "video_url": "javascript:alert(1)"}]}).json()
        assert saved["periods"][0]["video_url"] == "" and saved["periods"][0]["breakdown"]
        c.post(f"/api/sen/pupils/{ab['id']}/help", json={"message": "I'm stuck on step 2", "period": 1})
        assert c.get("/api/sen/help").json()[0]["code"] == "Y4-AB"
        _clean(c)
