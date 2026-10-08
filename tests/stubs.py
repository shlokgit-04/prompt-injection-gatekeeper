"""Test doubles ONLY (unit tests never need the model). The running
application itself never fakes Decider output; see tests/redteam for the
live suite that runs against a real strands-decider server."""
from decider.gate import QUESTION_SET


class StubDecider:
    """Returns preset noul probabilities when the preset label appears in the
    state; otherwise defaults (grounded/in_scope/proceed high, others low)."""

    def __init__(self, presets: dict[str, dict[str, float]], default: dict | None = None) -> None:
        self.presets = presets
        self.default = default or {
            "q_grounded": .95, "q_in_scope": .95, "q_risky": .05, "q_premature": .05,
            "q_proceed": .95, "q_confirm": .05, "q_deny": .05,
        }

    def ask(self, state, questions):
        for label, values in self.presets.items():
            if label in state:
                return {k: {"noul": values.get(k, self.default.get(k, 0.5))} for k in questions}
        return {k: {"noul": self.default.get(k, 0.5)} for k in questions}
