"""HTTP client for a strands-decider server.

Start one with (see scripts/run_decider.sh):
    strands-decider serve StrandsAgents/strands-decider-2B-hobson-v21 --port 8099

Requests are serialized with a lock: the upstream server currently mixes up
concurrent requests' probabilities (see strands-labs/strands-decider issues),
so a single client never has two questions in flight at once.
"""
from __future__ import annotations

import threading

import httpx


class DeciderError(RuntimeError):
    """The decider could not be reached or returned nothing usable."""


class DeciderClient:
    def __init__(self, base_url: str, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._lock = threading.Lock()

    def healthy(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=3.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def ask(self, state: str, questions: dict[str, dict]) -> dict[str, dict]:
        """Ask typed questions about one state.

        questions maps label -> {"type": "noul", "instructions": str}  (yes/no,
        answer carries "noul": P(true)). All question types noul/choice/score
        are documented in strands-decider docs/inference.md; the gate uses
        noul exclusively so every answer is a calibrated probability.
        """
        with self._lock:
            try:
                r = httpx.post(
                    f"{self.base_url}/v1/systemone",
                    json={"state": state, "questions": questions},
                    timeout=self.timeout_s,
                )
                r.raise_for_status()
                payload = r.json()
            except httpx.HTTPError as e:
                raise DeciderError(f"decider unreachable at {self.base_url}: {e}") from e
        answers = payload.get("answers") or {}
        if not answers:
            raise DeciderError(f"decider returned no answers: {payload}")
        return answers
