"""The boundary tests: a denied tool call must never reach the function body."""
from decider.gate import CONFIRM, DENY, PROCEED, Gate
from tests.stubs import StubDecider
from agent.gated_tools import ApprovalRequired, GatedTool, ToolDenied
from agent.approvals import Approvals
from backend.audit import AuditLog


def make_gate(action_map):
    class Fixed:
        def ask(self, state, questions):
            for label, values in action_map.items():
                if label in state:
                    return {k: {"noul": values.get(k, .5)} for k in questions}
            return {k: {"noul": .5} for k in questions}
    return Gate(Fixed())


def tool(action_map, action, audit, approvals):
    ran = []
    def spy(**kwargs):
        ran.append(kwargs); return {"status": "ok", "sent": True}
    g = make_gate(action_map)
    t = GatedTool("send_email", spy, g, audit, approvals)
    t.set_context(action, "")
    return t, ran


def test_deny_never_executes():
    audit = AuditLog("/tmp/data_test"); approvals = Approvals()
    t, ran = tool({"DENY": {"q_risky": .95, "q_deny": .9}}, "DENY", audit, approvals)
    try:
        t(**{"to": "outsider@evil.example", "subject": "s", "body": "b"})
        raised = False
    except ToolDenied:
        raised = True
    assert raised and ran == []  # function body never ran
    events = audit.recent()
    assert events and events[0]["execution"] == "blocked"

def test_confirm_holds_until_approved():
    audit = AuditLog("/tmp/data_test"); approvals = Approvals()
    t, ran = tool({"CONFIRM": {"q_confirm": .8}}, "CONFIRM", audit, approvals)
    try:
        t(**{"to": "x@y.z", "subject": "s", "body": "b"})
        raised = False
    except ApprovalRequired as e:
        raised = True; approval_id = e.approval_id
    assert raised and ran == [] and approval_id in {i["id"] for i in approvals.list_pending()}
    t.execute_approved({"to": "x@y.z", "subject": "s", "body": "b"})
    assert len(ran) == 1  # runs only after the human approves

def test_proceed_executes_and_audits():
    audit = AuditLog("/tmp/data_test"); approvals = Approvals()
    t, ran = tool({"PROCEED": {"q_proceed": .95, "q_grounded": .9, "q_in_scope": .9}}, "PROCEED", audit, approvals)
    r = t(**{"to": "me@here.example", "subject": "s", "body": "b"})
    assert len(ran) == 1 and r["tool_result"]["status"] == "ok"
    assert audit.recent()[0]["execution"] == "executed"
