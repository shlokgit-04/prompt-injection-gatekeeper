"""Human-approval queue for calls the gate marked CONFIRM."""
from __future__ import annotations

import itertools
import threading

_ids = itertools.count(1)


class Approvals:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}

    def enqueue(self, tool_name: str, args: dict, decision) -> str:
        approval_id = f"apr_{next(_ids):04d}"
        with self._lock:
            self._pending[approval_id] = {
                "id": approval_id, "tool": tool_name, "arguments": args,
                "decision": decision.to_dict(), "status": "pending",
            }
        return approval_id

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [v for v in self._pending.values() if v["status"] == "pending"]

    def resolve(self, approval_id: str, approve: bool) -> dict | None:
        with self._lock:
            item = self._pending.get(approval_id)
            if not item or item["status"] != "pending":
                return None
            item["status"] = "approved" if approve else "rejected"
            return item

    def get(self, approval_id: str) -> dict | None:
        with self._lock:
            return self._pending.get(approval_id)
