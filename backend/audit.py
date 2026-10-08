"""Append-only audit log for every intercepted tool call. JSONL on disk plus
in-memory for the UI. Values are redacted before they are written."""
from __future__ import annotations

import json
import os
import re
import threading
import time

_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)(password|token|secret|api[_-]?key)['\"]?\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_API_KEY]"),
]


def redact(value, key=None):
    if isinstance(value, dict):
        return {k: redact(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        if key and re.search(r"(?i)(password|token|secret|api[_-]?key|cookie)", key):
            return "[REDACTED]"
        for pat, repl in _SECRET_PATTERNS:
            value = pat.sub(repl, value)
        return value
    return value


class AuditLog:
    def __init__(self, data_dir: str) -> None:
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "audit.jsonl")
        self._lock = threading.Lock()
        self._events: list[dict] = []
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self._events = [json.loads(line) for line in f if line.strip()]

    def record(self, tool: str, args: dict, decision, execution: str,
               outcome: str, **extra) -> dict:
        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "tool": tool,
            "arguments": redact(args),
            "execution": execution,          # blocked | held | executed | error
            "outcome": outcome,
            **({"decision": decision.to_dict()} if decision else {}),
            **redact(extra),
        }
        with self._lock:
            self._events.append(event)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        return event

    def recent(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return list(reversed(self._events[-limit:]))
