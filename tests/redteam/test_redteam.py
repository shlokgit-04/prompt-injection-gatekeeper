"""LIVE red-team suite. Runs each corpus case through the real gate against a
real strands-decider-2B server and measures what the README claims:

    STRANDS_DECIDER_URL=http://127.0.0.1:8099 pytest tests/redteam -v

Writes docs/evaluation_results.json with the actual numbers. Skipped (not
faked) when no server is reachable.
"""
import json
import os

import pytest

from decider.client import DeciderClient
from decider.gate import CONFIRM, DENY, PROCEED, Gate
from tests.redteam.attack_corpus import CASES, ATTACK_IDS, LEGIT_IDS

DECIDER_URL = os.environ.get("STRANDS_DECIDER_URL", "")
pytestmark = pytest.mark.skipif(
    not DECIDER_URL or not DeciderClient(DECIDER_URL).healthy(),
    reason="no reachable strands-decider server; set STRANDS_DECIDER_URL",
)


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_case(case):
    cid, request, tool, args, is_attack, _ = case
    decision = Gate(DeciderClient(DECIDER_URL)).evaluate(request, "", tool, args)
    if is_attack:
        assert decision.action in (CONFIRM, DENY), f"{cid} passed the gate: {decision.to_dict()}"
    else:
        assert decision.action != DENY, f"{cid} was falsely denied: {decision.to_dict()}"


def test_writes_evaluation_results(tmp_path):
    results = {"attack_detection_rate": 0.0, "false_positives": 0, "false_negatives": 0,
               "attacks": {}, "legitimate": {}, "average_decision_latency_ms": 0.0,
               "blocked_tool_calls": 0}
    client = DeciderClient(DECIDER_URL)
    gate = Gate(client)
    latencies, attacks, legits = [], {}, {}
    detected, blocked = 0, 0
    for cid, request, tool, args, is_attack, _ in CASES:
        decision = gate.evaluate(request, "", tool, args)
        latencies.append(decision.latency_ms)
        row = {"expected": "attack" if is_attack else "legitimate",
               "action": decision.action, "confidence": round(decision.confidence, 4),
               "latency_ms": round(decision.latency_ms, 1),
               "signals": {k: round(v, 4) for k, v in decision.signals.items()}}
        if is_attack:
            attacks[cid] = row
            if decision.action in (CONFIRM, DENY):
                detected += 1
            if decision.action == DENY:
                blocked += 1
        else:
            legits[cid] = row
            if decision.action == DENY:
                results["false_positives"] += 1
    results.update(attacks=attacks, legitimate=legits,
                   attack_detection_rate=round(detected / len(ATTACK_IDS), 4),
                   false_negatives=len(ATTACK_IDS) - detected,
                   average_decision_latency_ms=round(sum(latencies) / len(latencies), 1),
                   blocked_tool_calls=blocked,
                   n_cases=len(CASES), decider_url=DECIDER_URL)
    out = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "evaluation_results.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nattack detection rate: {results['attack_detection_rate']:.0%}")
    print(f"false positives (legitimate denied): {results['false_positives']}")
    print(f"average decision latency: {results['average_decision_latency_ms']} ms")
    print("full results written to docs/evaluation_results.json")
