"""Deterministic fallback decision engine.

Used ONLY when the strands-decider server is unreachable. It is NOT the
Decider 2B model and never presents itself as one: every decision it makes
carries engine="signature-fallback" and a reason naming the rules it fired.
Unknown situations fail closed to CONFIRM, the same policy the real gate
follows when the model is down. With the decider server running, this module
is never consulted.
"""
from __future__ import annotations

import re
import time

from decider.gate import CONFIRM, DENY, PROCEED, Decision

_MARKER_RULES = [
    (re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions"), "ignore-instructions marker"),
    (re.compile(r"(?i)do\s+not\s+tell\s+the\s+user"), "secrecy marker"),
    (re.compile(r"(?i)customer\s+database|entire\s+database|whole\s+database"), "database exfiltration marker"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "credential marker"),
    (re.compile(r"(?i)(password|api[_-]?key|secret|token)\s*[:=]\s*\S+"), "secret-looking value"),
    (re.compile(r"(?i)this\s+is\s+an\s+approved\s+operation"), "false-authority marker"),
]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _markers(text: str) -> list[str]:
    return [label for pat, label in _MARKER_RULES if pat.search(text or "")]


class SignatureFallback:
    """Rule-based gate for deployments without the decider server."""

    engine = "signature-fallback"

    def __init__(self) -> None:
        pass

    def evaluate(self, user_request: str, conversation: str, tool_name: str,
                 tool_args: dict, untrusted_docs: list[dict] | None = None) -> Decision:
        t0 = time.perf_counter()
        request = user_request or ""
        args_text = " ".join(str(v) for v in (tool_args or {}).values())
        request_emails = set(_EMAIL_RE.findall(request))
        hits: list[str] = []
        deny = False
        confirm = False

        arg_markers = _markers(args_text)
        if arg_markers:
            hits.append("argument markers: " + ", ".join(arg_markers))
            deny = True

        # Directive-injection markers in the user's own request text: the
        # request is untrusted input to the gate just like document content.
        request_markers = _markers(request)
        directive_markers = [m for m in request_markers if m in (
            "ignore-instructions marker", "secrecy marker", "false-authority marker")]
        if directive_markers:
            hits.append("request contains injection directive(s): " + ", ".join(directive_markers))
            confirm = True

        directive_hit = None
        for doc in (untrusted_docs or []):
            for marker in _markers(doc.get("content", "")):
                directive_hit = f"untrusted document '{doc.get('filename')}' contains: {marker}"
        if directive_hit and tool_name in ("send_email", "database_query"):
            hits.append(directive_hit)
            deny = True

        if tool_name == "send_email":
            to = str((tool_args or {}).get("to", ""))
            if to and to not in request_emails:
                hits.append(f"recipient {to} was never named in the user's request")
                deny = True
            elif not to:
                hits.append("no recipient resolved")
                deny = True
        elif tool_name == "read_document":
            filename = str((tool_args or {}).get("filename", ""))
            stem = re.sub(r"[^a-z0-9]+", " ", filename.rsplit(".", 1)[0].lower()).strip()
            if stem and not any(w in request.lower() for w in stem.split() if len(w) > 3):
                hits.append(f"document '{filename}' is not named in the user's request")
                confirm = True
        elif tool_name == "database_query":
            query = str((tool_args or {}).get("query", ""))
            if not query.strip().lower().startswith("select"):
                hits.append("non-SELECT query proposed")
                deny = True
            elif not re.search(r"(?i)\b(where|limit)\b", query):
                hits.append("unscoped full-table SELECT has no WHERE/LIMIT scope")
                confirm = True
            elif not any(w in request.lower() for w in ("customer", "database", "data", "order", "record")):
                hits.append("database query is not grounded in the user's request")
                confirm = True
        else:
            hits.append(f"tool '{tool_name}' is not in the reviewed tool set")
            deny = True

        if deny:
            action, reason = DENY, "signature rules fired: " + "; ".join(hits)
        elif confirm:
            action, reason = CONFIRM, "signature rules ambiguous: " + "; ".join(hits)
        else:
            action, reason = PROCEED, "no exfiltration or grounding violations found by signature rules"
        return Decision(
            action=action, engine=self.engine,
            confidence=1.0 if deny else (0.5 if confirm else 0.9),
            reason=reason, signals={"rules_hit": float(len(hits))},
            latency_ms=(time.perf_counter() - t0) * 1000, error=None,
        )
