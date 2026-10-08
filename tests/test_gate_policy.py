from decider.gate import CONFIRM, DENY, PROCEED, Gate
from tests.stubs import StubDecider

def sig(grounded=.95, in_scope=.95, risky=.05, premature=.05, proceed=.95, confirm=.05, deny=.05):
    return {"q_grounded": grounded, "q_in_scope": in_scope, "q_risky": risky,
            "q_premature": premature, "q_proceed": proceed, "q_confirm": confirm, "q_deny": deny}

def preset(m):
    return {f"call {m}": sig(**m)}

def make(preset_map):
    s = StubDecider({f"call {k}": sig(**v) for k, v in preset_map.items()})
    return Gate(s), s

def test_safe_call_proceeds():
    g, _ = make({"a": {}})
    d = g.evaluate("call a", "", "read_document", {"filename": "x.md"})
    assert d.action == PROCEED and d.confidence > 0.9 and d.error is None

def test_risky_call_denied():
    g, _ = make({"a": {"risky": .9, "deny": .8, "proceed": .05}})
    d = g.evaluate("call a", "", "database_query", {"query": "SELECT * FROM customers"})
    assert d.action == DENY

def test_ungrounded_arguments_require_human():
    g, _ = make({"a": {"grounded": .4, "confirm": .6, "proceed": .2}})
    d = g.evaluate("call a", "", "send_email", {"to": "x@y.z", "subject": "s", "body": "b"})
    assert d.action == CONFIRM

def test_out_of_scope_call_held():
    g, _ = make({"a": {"in_scope": .3, "confirm": .7, "proceed": .1}})
    d = g.evaluate("call a", "", "database_query", {"query": "SELECT * FROM customers"})
    assert d.action == CONFIRM

def test_premature_call_held():
    g, _ = make({"a": {"premature": .8, "confirm": .5, "proceed": .2}})
    d = g.evaluate("call a", "", "send_email", {"to": "x@y.z", "subject": "s", "body": "b"})
    assert d.action == CONFIRM

def test_decider_down_fails_closed():
    class Down:
        def ask(self, *a, **k): raise RuntimeError("connection refused")
    d = Gate(Down()).evaluate("r", "", "send_email", {"to": "x@y.z", "subject": "s", "body": "b"})
    assert d.action == CONFIRM and d.error is not None
