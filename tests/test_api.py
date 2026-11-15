import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["GATEKEEPER_SECRET_KEY"] = "test-secret-key-0123456789abcdef0123456789abcdef"
os.environ["DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["DOCUMENTS_DIR"] = os.path.join(os.path.dirname(__file__), "..", "demo", "documents")
os.environ.pop("STRANDS_DECIDER_URL", None)
os.environ.pop("OPENROUTER_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
from backend.app import app  # noqa: E402

c = TestClient(app)


def register(email):
    r = c.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_auth_flow():
    r = c.get("/api/auth/me")
    assert r.status_code == 401
    h = register(f"t{os.urandom(4).hex()}@test.local")
    me = c.get("/api/auth/me", headers=h)
    assert me.status_code == 200 and "engine" in me.json()["user"]
    bad = c.post("/api/auth/login", json={"email": "x@y.z", "password": "wrong-pass-1"})
    assert bad.status_code == 401


def test_health_and_documents():
    h = c.get("/api/health")
    assert h.status_code == 200 and h.json()["engine"] == "signature-fallback"
    docs = c.get("/api/documents").json()
    names = {d["filename"] for d in docs}
    assert "vendor_terms_malicious.md" in names


def test_safe_run_proceeds_and_emails():
    h = register(f"s{os.urandom(4).hex()}@test.local")
    r = c.post("/api/run", headers=h, json={
        "message": "Read the supplier invoice and email a summary to boss@corp.example"})
    steps = r.json()["steps"]
    tools = [s["tool"] for s in steps]
    assert "read_document" in tools and "send_email" in tools
    assert all(s["decision"]["action"] == "PROCEED" for s in steps)
    assert c.get("/api/outbox", headers=h).json()[0]["recipient"] == "boss@corp.example"


def test_injection_run_denies():
    h = register(f"i{os.urandom(4).hex()}@test.local")
    r = c.post("/api/run", headers=h, json={
        "message": "Read the vendor terms document and tell me if we can ship"})
    denied = [s for s in r.json()["steps"] if s["decision"]["action"] == "DENY"]
    assert denied and denied[0]["tool"] == "send_email"
    assert denied[0]["decision"]["engine"] == "signature-fallback"
    assert c.get("/api/outbox", headers=h).json() == []


def test_ambiguous_run_holds_for_approval():
    h = register(f"a{os.urandom(4).hex()}@test.local")
    r = c.post("/api/run", headers=h, json={"message": "Run the quarterly numbers query"})
    held = [s for s in r.json()["steps"] if s["decision"]["action"] == "CONFIRM"]
    assert held and held[0]["execution"] == "held" and held[0]["approval_id"]
    pend = c.get("/api/pending", headers=h).json()
    assert len(pend) == 1 and pend[0]["id"] == held[0]["approval_id"]


def test_approvals_are_per_user():
    ha = register(f"u1{os.urandom(4).hex()}@test.local")
    c.post("/api/run", headers=ha, json={"message": "Run the quarterly numbers query"})
    hb = register(f"u2{os.urandom(4).hex()}@test.local")
    aid = c.get("/api/pending", headers=ha).json()[0]["id"]
    assert c.get("/api/pending", headers=hb).json() == []
    assert c.post(f"/api/pending/{aid}/approve", headers=hb).status_code == 404
    ok = c.post(f"/api/pending/{aid}/approve", headers=ha)
    assert ok.status_code == 200 and ok.json()["status"] == "executed"
    assert c.post(f"/api/pending/{aid}/approve", headers=ha).status_code == 404


def test_audit_is_per_user_and_redacted():
    h = register(f"au{os.urandom(4).hex()}@test.local")
    c.post("/api/run", headers=h, json={"message": "Read the supplier invoice"})
    log = c.get("/api/audit", headers=h).json()
    assert log and log[0]["tool"] in ("read_document",)
    h2 = register(f"au2{os.urandom(4).hex()}@test.local")
    assert c.get("/api/audit", headers=h2).json() == []


def test_policy_and_export_and_delete():
    h = register(f"p{os.urandom(4).hex()}@test.local")
    r = c.put("/api/policy", headers=h, json={"deny_risk": 0.9})
    assert r.json()["deny_risk"] == 0.9
    r = c.put("/api/policy", headers=h, json={"deny_risk": 5})
    assert r.json()["deny_risk"] == 0.95
    ex = c.get("/api/auth/export", headers=h)
    assert ex.status_code == 200 and "audit" in ex.json()
    assert c.delete("/api/auth/me", headers=h).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401


def test_rate_limit_and_bad_input():
    h = register(f"r{os.urandom(4).hex()}@test.local")
    assert c.post("/api/run", headers=h, json={"message": "x" * 5000}).status_code == 400
    codes = [c.post("/api/run", headers=h, json={"message": "Run the quarterly numbers query"}).status_code
             for _ in range(25)]
    assert 429 in codes


def test_security_headers():
    r = c.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
