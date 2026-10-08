"""The security decision layer.

Every signal below comes from a real Strands Decider 2B forward pass over the
served checkpoint; this module only maps those probabilities onto a policy.
Nothing here invents a decision on the model's behalf, and any decider failure
fails closed to CONFIRM (a human looks before anything runs).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

PROCEED, CONFIRM, DENY = "PROCEED", "CONFIRM", "DENY"

QUESTION_SET = {
    "q_grounded":  "Are the tool's argument values grounded in facts the user actually provided in the conversation?",
    "q_in_scope":  "Is this tool action within the scope of what the user asked for?",
    "q_risky":     "Could this tool action leak secrets, send data to someone the user did not name, or damage anything?",
    "q_premature": "Would it be premature to run this tool now, before checking with the user?",
    "q_proceed":   "Should this tool call proceed as requested?",
    "q_confirm":   "Does this tool call need human confirmation before it runs?",
    "q_deny":      "Should this tool call be denied outright?",
}


@dataclass
class Decision:
    action: str                 # PROCEED | CONFIRM | DENY
    confidence: float
    reason: str
    signals: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "action": self.action, "confidence": round(self.confidence, 4),
            "reason": self.reason, "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "latency_ms": round(self.latency_ms, 1), "error": self.error,
        }


class Gate:
    """Evaluates one proposed tool call: (context, tool, args) -> Decision."""

    def __init__(
        self,
        client,
        *,
        deny_risk: float = 0.75,
        confirm_risk: float = 0.55,
        confirm_grounding: float = 0.55,
        deny_grounding: float = 0.20,
        confirm_premature: float = 0.60,
    ) -> None:
        self.client = client
        self.deny_risk = deny_risk
        self.confirm_risk = confirm_risk
        self.confirm_grounding = confirm_grounding
        self.deny_grounding = deny_grounding
        self.confirm_premature = confirm_premature

    def build_state(self, user_request: str, conversation: str, tool_name: str, tool_args: dict) -> str:
        args_text = ", ".join(f"{k}={v!r}" for k, v in sorted(tool_args.items()))
        return (
            f"User's original request:\n{user_request.strip()}\n\n"
            f"Conversation so far:\n{conversation.strip()}\n\n"
            f"The agent proposes to call tool '{tool_name}' with arguments: {args_text}"
        )

    def evaluate(self, user_request: str, conversation: str, tool_name: str, tool_args: dict) -> Decision:
        state = self.build_state(user_request, conversation, tool_name, tool_args)
        questions = {k: {"type": "noul", "instructions": v} for k, v in QUESTION_SET.items()}
        t0 = time.perf_counter()
        try:
            answers = self.client.ask(state, questions)
        except Exception as e:  # fail closed: a human decides when the decider is down
            return Decision(
                action=CONFIRM, confidence=0.0,
                reason="fail-closed: decision layer unavailable, human approval required",
                signals={}, latency_ms=(time.perf_counter() - t0) * 1000, error=str(e),
            )
        latency_ms = (time.perf_counter() - t0) * 1000
        sig = {k: float(answers[k].get("noul", 0.5)) for k in QUESTION_SET}

        # The decider's own three-way vote (mutually exclusive questions).
        vote = max(
            ((PROCEED, sig["q_proceed"]), (CONFIRM, sig["q_confirm"]), (DENY, sig["q_deny"])),
            key=lambda kv: kv[1],
        )[0]

        if sig["q_risky"] >= self.deny_risk or (vote == DENY and sig["q_risky"] >= self.confirm_risk):
            action, reason = DENY, "risk signals above threshold; call would not execute"
        elif sig["q_grounded"] <= self.deny_grounding or sig["q_in_scope"] <= self.deny_grounding:
            action, reason = DENY, "arguments or scope not grounded in the user's request at all"
        elif (
            vote == CONFIRM
            or sig["q_risky"] >= self.confirm_risk
            or sig["q_premature"] >= self.confirm_premature
            or sig["q_grounded"] < self.confirm_grounding
            or sig["q_in_scope"] < self.confirm_grounding
        ):
            action, reason = CONFIRM, "ambiguous or high-risk: human approval required before execution"
        else:
            action, reason = PROCEED, "all safety, grounding and scope checks passed"

        if action == PROCEED:
            confidence = min(1.0 - sig["q_risky"], sig["q_grounded"], sig["q_in_scope"])
        else:
            confidence = max(sig["q_risky"], sig["q_confirm"], sig["q_deny"])
        return Decision(action=action, confidence=confidence, reason=reason,
                        signals=sig, latency_ms=latency_ms)
