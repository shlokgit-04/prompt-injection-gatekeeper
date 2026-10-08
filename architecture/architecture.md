# Architecture

```
Frontend (static UI)
   |
FastAPI backend
   |
Strands Agent (main LLM on Amazon Bedrock)
   |
proposed tool call
   |
GatedTool boundary (agent/gated_tools.py)      <- the only path to real tools
   |
Gate decision layer (decider/gate.py)
   |
Strands Decider 2B server (local HTTP, v21 checkpoint)
   |
PROCEED / CONFIRM / DENY
   |
Tools: read_document | send_email | database_query
   |
AuditLog (append-only, redacted) + human approval queue
```

Cloud shape (docs/deployment.md): one AWS compute task running the backend
and the decider sidecar; Bedrock for the agent LLM; no GPU by default.
