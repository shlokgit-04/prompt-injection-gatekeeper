"""Prompt-Injection Gatekeeper: full-stack app.

Real accounts (bcrypt + signed 30-day sessions), per-user audit / approvals /
messages / outbox / policy in SQLite, and the same tool-boundary security
model as before: every proposed tool call passes the decision layer before it
executes, DENY never reaches a real tool, CONFIRM parks for a human, PROCEED
is audited. When the strands-decider server is reachable it supplies the
signals (engine "decider-2b"); when it is not, a clearly labeled deterministic
signature engine (decider/fallback.py) decides instead and unknowns fail
closed to CONFIRM. The running application never fabricates model output.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from agent.gated_tools import GatedTool
from agent.proposer import propose
from backend.audit import redact
from backend.security import (SECURITY_HEADERS, RateLimiter, TokenSigner,
                              check_password, hash_password, valid_email)
from backend.store import Store
from decider.client import DeciderClient
from decider.fallback import SignatureFallback
from decider.gate import CONFIRM, DENY, PROCEED, Decision, Gate
from tools.database_query import database_query
from tools.read_document import read_document
from tools.send_email import send_email

DATA_DIR = os.environ.get("DATA_DIR", "./data")
DOCUMENTS_DIR = os.environ.get("DOCUMENTS_DIR", "./demo/documents")
DECIDER_URL = os.environ.get("STRANDS_DECIDER_URL", "").strip()
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

app = FastAPI(title="Prompt-Injection Gatekeeper")
_ALLOWED_ORIGINS = ["https://shlok.is-a.dev", "https://shlokgit-04.github.io",
                    "http://localhost:8080", "http://localhost:8081",
                    "http://127.0.0.1:8080", "http://127.0.0.1:8081"]
app.add_middleware(CORSMiddleware, allow_origins=_ALLOWED_ORIGINS,
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                   allow_headers=["authorization", "content-type"], max_age=600)

store = Store(os.path.join(DATA_DIR, "gatekeeper.db"))
signer = TokenSigner(os.environ.get("GATEKEEPER_SECRET_KEY", ""))
limiter = RateLimiter()
decider = DeciderClient(DECIDER_URL) if DECIDER_URL else None
fallback = SignatureFallback()
_health_cache: dict = {"ok": False, "ts": 0.0}


def seed_demo_db() -> None:
    db = os.path.join(DATA_DIR, "customers.db")
    if os.path.exists(db):
        return
    conn = sqlite3.connect(db)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT, company TEXT, email TEXT);
    CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, customer_id INTEGER, item TEXT, amount REAL);
    INSERT INTO customers VALUES (1,'Asha Sharma','Nimbus Logistics','asha@nimbus.example');
    INSERT INTO customers VALUES (2,'Ravi Menon','Peak Foods','ravi@peakfoods.example');
    INSERT INTO orders VALUES (101,1,'pallet racking',12000.00);
    INSERT INTO orders VALUES (102,2,'cold-chain sensors',8400.00);
    """)
    conn.commit()
    conn.close()


seed_demo_db()


def decider_healthy() -> bool:
    if not decider:
        return False
    if time.monotonic() - _health_cache["ts"] < 60:
        return _health_cache["ok"]
    ok = decider.healthy()
    _health_cache.update({"ok": ok, "ts": time.monotonic()})
    return ok


def engine_name() -> str:
    return "decider-2b" if decider_healthy() else "signature-fallback"


def evaluate_gated(user_request: str, conversation: str, tool_name: str,
                   tool_args: dict, untrusted_docs: list[dict], thresholds: dict) -> Decision:
    if decider_healthy():
        gate = Gate(decider, **thresholds)
        return gate.evaluate(user_request, conversation, tool_name, tool_args)
    return fallback.evaluate(user_request, conversation, tool_name, tool_args, untrusted_docs)


def run_tool(uid: int, name: str, args: dict) -> dict:
    if name == "read_document":
        return read_document(**args)
    if name == "send_email":
        result = send_email(outbox_dir=os.path.join(DATA_DIR, "outbox", str(uid)), **args)
        if result.get("status") in ("written_to_outbox", "sent"):
            store.outbox_add(uid, result.get("to", ""), args.get("subject", ""),
                             str(args.get("body", ""))[:8000])
        return result
    if name == "database_query":
        db = os.path.join(DATA_DIR, "customers.db")
        conn = sqlite3.connect(db)
        try:
            q = args.get("query", "").strip().rstrip(";").strip()
            if not q.lower().startswith("select"):
                return {"status": "refused", "reason": "only SELECT statements are allowed"}
            cur = conn.execute(q)
            cols = [d[0] for d in cur.description]
            return {"status": "ok", "columns": cols, "rows": cur.fetchmany(50)}
        except sqlite3.Error as e:
            return {"status": "error", "reason": str(e)}
        finally:
            conn.close()
    return {"status": "refused", "reason": f"tool '{name}' is not in the reviewed tool set"}


class AuthRequest(BaseModel):
    email: str
    password: str


class RunRequest(BaseModel):
    message: str
    model_id: str | None = None


class PolicyRequest(BaseModel):
    deny_risk: float | None = None
    confirm_risk: float | None = None
    confirm_grounding: float | None = None
    deny_grounding: float | None = None
    confirm_premature: float | None = None


def auth_user(req: Request) -> dict | None:
    token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return None
    data = signer.verify(token)
    if not data:
        return None
    user = store.user_by_id(data["uid"])
    if not user or user["token_version"] != data["tv"]:
        return None
    return user


def require(req: Request):
    user = auth_user(req)
    if not user:
        raise PermissionError
    return user


@app.middleware("http")
async def headers_and_rate_limit(request: Request, call_next):
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or "local"
    bucket = f"{ip}:{request.url.path}"
    limited = request.method == "POST" and (
        (request.url.path.startswith("/api/auth/") and not limiter.allow(bucket, 10, 60))
        or (request.url.path == "/api/run" and not limiter.allow(bucket, 20, 60)))
    if limited:
        return JSONResponse(status_code=429, content={"error": "rate limit, slow down"},
                            headers=SECURITY_HEADERS)
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "decider_url_set": bool(decider), "engine": engine_name(),
            "llm_attached": bool(OPENROUTER_KEY)}


@app.post("/api/auth/register")
def register(req: AuthRequest):
    if not valid_email(req.email):
        return JSONResponse(status_code=400, content={"error": "enter a valid email address"})
    if len(req.password) < 8:
        return JSONResponse(status_code=400, content={"error": "password must be at least 8 characters"})
    try:
        uid = store.create_user(req.email.strip().lower(), hash_password(req.password))
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    user = store.user_by_id(uid)
    return {"token": signer.issue(uid, user["token_version"]), "email": user["email"]}


@app.post("/api/auth/login")
def login(req: AuthRequest):
    user = store.user_by_email(req.email.strip().lower())
    if not user or not check_password(req.password, user["pw_hash"]):
        return JSONResponse(status_code=401, content={"error": "wrong email or password"})
    return {"token": signer.issue(user["id"], user["token_version"]), "email": user["email"]}


@app.get("/api/auth/me")
def me(request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    return {"user": {"email": user["email"], "created_at": user["created_at"],
                     "engine": engine_name()}}


@app.delete("/api/auth/me")
def delete_account(request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    store.bump_token_version(user["id"])
    store.delete_user(user["id"])
    return {"status": "deleted"}


@app.get("/api/auth/export")
def export_data(request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    uid = user["id"]
    return {"user": {"email": user["email"], "created_at": user["created_at"]},
            "policy": store.policy_get(uid), "messages": store.messages_recent(uid, 100),
            "audit": store.audit_recent(uid, 500), "outbox": store.outbox_recent(uid, 200)}


def list_documents() -> list[dict]:
    docs = []
    if os.path.isdir(DOCUMENTS_DIR):
        for fn in sorted(os.listdir(DOCUMENTS_DIR)):
            if fn.endswith((".md", ".txt")):
                with open(os.path.join(DOCUMENTS_DIR, fn), encoding="utf-8", errors="replace") as f:
                    docs.append({"filename": fn, "content": f.read(20000)})
    return docs


@app.get("/api/documents")
def documents():
    return [{"filename": d["filename"]} for d in list_documents()]


@app.post("/api/run")
def run(req: RunRequest, request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    uid = user["id"]
    message = req.message.strip()
    if not message or len(message) > 4000:
        return JSONResponse(status_code=400, content={"error": "message must be 1-4000 characters"})

    conversation = "\n".join(f"{m['role']}: {m['content']}" for m in store.messages_recent(uid, 6))
    thresholds = store.policy_get(uid)
    docs = list_documents()
    steps: list[dict] = []
    read_results: list[dict] = []
    done: set[tuple] = set()

    def process(proposals: list[dict]) -> None:
        for p in proposals:
            key = (p["tool"], tuple(sorted((k, str(v)) for k, v in p["args"].items())))
            if key in done:
                continue
            done.add(key)
            tool, args = p["tool"], p["args"]
            seen_docs = [{"filename": r.get("filename"), "content": r.get("content", "")}
                         for r in read_results]
            decision = evaluate_gated(message, conversation, tool, args, seen_docs, thresholds)
            decision.source = p["source"]
            if decision.action == DENY:
                store.audit_record(uid, tool, redact(args), "blocked", "denied_by_gate", decision.to_dict())
                steps.append({"tool": tool, "args": redact(args), "source": p["source"],
                              "decision": decision.to_dict(), "execution": "blocked", "result": None})
            elif decision.action == CONFIRM:
                approval_id = f"apr_{uid}_{int(time.time() * 1000)}_{len(steps)}"
                store.approval_enqueue(uid, approval_id, tool, redact(args), decision.to_dict())
                store.audit_record(uid, tool, redact(args), "held", "awaiting_approval",
                                   decision.to_dict(), approval_id)
                steps.append({"tool": tool, "args": redact(args), "source": p["source"],
                              "decision": decision.to_dict(), "execution": "held",
                              "result": None, "approval_id": approval_id})
            else:
                try:
                    result = run_tool(uid, tool, args)
                    if tool == "read_document" and result.get("status") == "ok":
                        read_results.append(result)
                    store.audit_record(uid, tool, redact(args), "executed",
                                       "auto_proceed", decision.to_dict())
                    steps.append({"tool": tool, "args": redact(args), "source": p["source"],
                                  "decision": decision.to_dict(), "execution": "executed",
                                  "result": result})
                except Exception as e:  # noqa: BLE001 - audited failure path
                    store.audit_record(uid, tool, redact(args), "error", "execution_error")
                    steps.append({"tool": tool, "args": redact(args), "source": p["source"],
                                  "decision": decision.to_dict(), "execution": "error",
                                  "result": {"error": str(e)}})

    process(propose(message, docs, read_results))
    for _ in range(2):  # a read can surface directives that propose new calls
        before = len(steps)
        process(propose(message, docs, read_results))
        if len(steps) == before:
            break

    if not steps:
        reply = ("No tool call proposed. Try: 'Read the supplier invoice and email a summary "
                 "to you@company.example' or 'Query the customer database'.")
        store.message_add(uid, "user", message)
        store.message_add(uid, "assistant", reply)
        return {"status": "ok", "reply": reply, "steps": [], "engine": engine_name()}

    denied = sum(1 for s in steps if s["decision"]["action"] == DENY)
    held = sum(1 for s in steps if s["decision"]["action"] == CONFIRM)
    ran = sum(1 for s in steps if s["decision"]["action"] == PROCEED)
    reply = f"{ran} call(s) executed, {held} held for your approval, {denied} denied. Engine: {engine_name()}."
    store.message_add(uid, "user", message, {"steps": len(steps)})
    store.message_add(uid, "assistant", reply, {"engine": engine_name()})
    return {"status": "ok", "reply": reply, "steps": steps, "engine": engine_name()}


@app.get("/api/pending")
def pending(request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    return store.approvals_pending(user["id"])


@app.post("/api/pending/{approval_id}/approve")
def approve(approval_id: str, request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    item = store.approval_resolve(user["id"], approval_id, True)
    if not item:
        return JSONResponse(status_code=404, content={"error": "unknown or already resolved"})
    result = run_tool(user["id"], item["tool"], item["arguments"])
    store.audit_record(user["id"], item["tool"], redact(item["arguments"]), "executed",
                       "human_approved", item.get("decision"), approval_id)
    return {"status": "executed", "result": result, "approval": approval_id}


@app.post("/api/pending/{approval_id}/reject")
def reject(approval_id: str, request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    item = store.approval_resolve(user["id"], approval_id, False)
    if not item:
        return JSONResponse(status_code=404, content={"error": "unknown or already resolved"})
    store.audit_record(user["id"], item["tool"], redact(item["arguments"]), "blocked",
                       "rejected_by_human", item.get("decision"), approval_id)
    return {"status": "rejected", "approval": approval_id}


@app.get("/api/audit")
def audit(request: Request, limit: int = 100):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    return store.audit_recent(user["id"], limit)


@app.get("/api/outbox")
def outbox(request: Request, limit: int = 50):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    return store.outbox_recent(user["id"], limit)


@app.get("/api/policy")
def get_policy(request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    return store.policy_get(user["id"])


@app.put("/api/policy")
def put_policy(body: PolicyRequest, request: Request):
    try:
        user = require(request)
    except PermissionError:
        return JSONResponse(status_code=401, content={"error": "not signed in"})
    return store.policy_set(user["id"], body.model_dump(exclude_none=True))


FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]


@app.get("/api/models")
def models():
    if not OPENROUTER_KEY:
        return {"available": False,
                "note": "no main LLM attached; runs use the scripted proposal mode"}
    return {"available": True, "models": FREE_MODELS}


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html"))
