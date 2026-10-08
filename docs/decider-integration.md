# Decider 2B integration

Checkpoint: strands-decider-2B-hobson-v21 (the published reference model),
served locally with `strands-decider serve ... --port 8099` (Apache-2.0,
code and training recipe public at strands-labs/strands-decider).

## Why a decision model and not the main LLM
The gate runs on every tool call. Its checks are narrow classification
problems with calibrated confidence; Decider 2B answers a typed question in
~115 ms on a consumer GPU locally, cheaply enough to sit on the hot path,
where an LLM call never could. Its published calibration rule (0.9+ right
~95% of the time on unseen short tasks; below that, confirm with a person)
is exactly the product's three-state contract.

## The question set (decider/gate.py)
All questions are `noul` type (yes/no, returned as P(true)), the documented
request shape of POST /v1/systemone. Seven questions on one shared state,
so each question adds only its own tokens (shared-prefix cache):

q_grounded, q_in_scope, q_risky, q_premature, q_proceed, q_confirm, q_deny.

The last three are mutually exclusive and give the model its own three-way
vote; the first four are the checks the policy thresholds branch on.

## The decision (decider/gate.py)
See README's "The decision, exactly" for the threshold table. Confidence is
the probability of the chosen action's supporting signal (for PROCEED: the
minimum of 1-risk, grounding, scope). Failure is fail-closed: any error
returns CONFIRM, and the audit record carries the error string.

## Honesty rules the implementation follows
- The running application only reads Decider 2B probabilities; it never
  fabricates them.
- Unit tests use a stubbed client explicitly labeled a test double; the LIVE
  red-team suite (tests/redteam) runs against the real server and is skipped,
  not faked, when no server is reachable.
- Concurrency: the upstream server currently mixes up concurrent requests'
  probabilities, so the client serializes requests (decider/client.py).
