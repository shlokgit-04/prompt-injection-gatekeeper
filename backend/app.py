"""FastAPI app: chat, human approvals, audit log, live decision trace."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from agent.approvals import Approvals
from agent.gated_tools import ApprovalRequired, GatedTool, ToolDenied
from agent.main import build_stack
from backend.audit import AuditLog
from decider.client import DeciderClient
from decider.gate import Gate
from tools.database_query import database_query
from tools.read_document import read_document
from tools.send_email import send_email

app = FastAPI(title="Prompt-Injection Gatekeeper")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

gate_client = DeciderClient(os.environ.get("STRANDS_DECIDER_URL", "http://127.0.0.1:8099"))
gate = Gate(gate_client)
audit = AuditLog(os.environ.get("DATA_DIR", "./data"))
approvals = Approvals()

gated = {
    name: GatedTool(name, fn, gate, audit, approvals)
    for name, fn in [("read_document", read_document),
                     ("send_email", send_email),
                     ("database_query", database_query)]
}


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
def health():
    return {"decider": gate_client.healthy()}


@app.post("/chat")
def chat(req: ChatRequest):
    for tool in gated.values():
        tool.set_context(req.message, "")
    try:
        agent, _ = build_stack()
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    try:
        response = agent(req.message)
        return {"status": "ok", "response": str(response)}
    except ToolDenied as e:
        return {"status": "denied", "decision": e.decision, "detail": str(e)}
    except ApprovalRequired as e:
        return {"status": "approval_required", "approval_id": e.approval_id,
                "decision": e.decision, "tool": e.tool_name, "arguments": e.tool_args}


@app.get("/pending")
def pending():
    return approvals.list_pending()


@app.post("/pending/{approval_id}/approve")
def approve(approval_id: str):
    item = approvals.resolve(approval_id, True)
    if not item:
        return JSONResponse(status_code=404, content={"error": "unknown or already resolved"})
    tool = gated[item["tool"]]
    result = tool.execute_approved(item["arguments"])
    return {"status": "executed", "result": result, "approval": approval_id}


@app.post("/pending/{approval_id}/reject")
def reject(approval_id: str):
    item = approvals.resolve(approval_id, False)
    if not item:
        return JSONResponse(status_code=404, content={"error": "unknown or already resolved"})
    return {"status": "rejected", "approval": approval_id}


@app.get("/audit")
def audit_log(limit: int = 100):
    return audit.recent(limit)


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html"))
