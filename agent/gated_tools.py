"""The tool-call boundary.

agent/main.py builds the Strands agent ONLY with tools wrapped by GatedTool,
so there is no path from the LLM's tool choice to a real function that does
not pass through the gate. A DENIED call raises before the function body;
a CONFIRM call parks in the approval queue and only runs after a human says
so; a PROCEED call runs and is audited either way.
"""
from __future__ import annotations

from decider.gate import CONFIRM, DENY, PROCEED, Gate


class ToolDenied(Exception):
    def __init__(self, message: str, decision: dict) -> None:
        super().__init__(message)
        self.decision = decision


class ApprovalRequired(Exception):
    def __init__(self, approval_id: str, tool_name: str, tool_args: dict, decision: dict) -> None:
        super().__init__(f"approval {approval_id} required for {tool_name}")
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.decision = decision


class GatedTool:
    """Wraps a plain function so every invocation passes the Decider 2B gate."""

    def __init__(self, name: str, fn, gate: Gate, audit, approvals,
                 user_request: str = "", conversation: str = "") -> None:
        self.name = name
        self.fn = fn
        self.gate = gate
        self.audit = audit
        self.approvals = approvals
        self.user_request = user_request
        self.conversation = conversation

    def set_context(self, user_request: str, conversation: str) -> None:
        self.user_request, self.conversation = user_request, conversation

    def __call__(self, **kwargs) -> dict:
        decision = self.gate.evaluate(self.user_request, self.conversation, self.name, kwargs)
        if decision.action == DENY:
            self.audit.record(self.name, kwargs, decision, execution="blocked", outcome="denied_by_gate")
            raise ToolDenied(
                f"Security layer denied tool '{self.name}': {decision.reason}", decision.to_dict()
            )
        if decision.action == CONFIRM:
            approval_id = self.approvals.enqueue(self.name, kwargs, decision)
            self.audit.record(self.name, kwargs, decision, execution="held", outcome="awaiting_approval",
                              approval_id=approval_id)
            raise ApprovalRequired(approval_id, self.name, kwargs, decision.to_dict())
        result = self._run_audited(kwargs, "auto_proceed")
        return {"tool_result": result, "decision": decision.to_dict()}

    def execute_approved(self, kwargs: dict) -> dict:
        """Runs after a human approves a CONFIRM call. Still audited."""
        return self._run_audited(kwargs, "human_approved")

    def _run_audited(self, kwargs: dict, mode: str) -> dict:
        try:
            result = self.fn(**kwargs)
            self.audit.record(self.name, kwargs, decision=None, execution="executed",
                              outcome=mode, result_status=str(result.get("status", "ok")))
            return result
        except Exception as e:
            self.audit.record(self.name, kwargs, decision=None, execution="error",
                              outcome=mode, error=str(e))
            raise
