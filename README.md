# Prompt-Injection Gatekeeper

A security/decision layer for AI agents. A Strands agent (Strands Agents SDK,
main LLM on Amazon Bedrock) proposes tool calls; **Strands Decider 2B**, a
2B-parameter decision model served locally, evaluates every proposed call at
the tool boundary before it executes, and the layer maps the model's
calibrated probabilities onto **PROCEED / CONFIRM (human approval) / DENY**.

Agents can be manipulated: an untrusted document, email, or web page can
hijack an agent into exfiltrating data. This system makes sure a denied tool
call never reaches a real tool, and every interception is audited.

## WHAT / WHY / HOW

- **WHAT:** an agent with three real tools (read a document, send email,
  query a customer database) whose every tool call passes through a decision
  layer powered by Strands Decider 2B before execution.
- **WHY an agent:** the interesting security failure mode is agentic: an LLM
  with tools follows instructions it finds in untrusted content. A chatbot
  cannot be prompt-injected into *doing* anything; an agent can.
- **WHY Decider 2B:** the gate's checks (grounding, scope, risk, prematurity)
  are narrow classification problems. Decider 2B answers them in ~115 ms per
  question locally with calibrated confidence, cheaply enough to sit on every
  tool call, where an LLM call never could. Its calibration rule is the
  product's rule too: at confidence 0.9+ it is right ~95% of the time; below
  that, confirm with a person.
- **WHY AWS:** the agent's main LLM runs on Amazon Bedrock through the
  Strands Agents SDK; deployment target is AWS (see docs/deployment.md).
- **HOW security works:** every tool the agent's registry holds is a
  `GatedTool` wrapper (agent/gated_tools.py). There is no path from the LLM's
  tool choice to a real function that does not pass the gate. A DENYED call
  raises before the function body runs; a CONFIRM call parks in the approval
  queue and only runs after a human approves it in the UI; a PROCEED call
  runs and is audited. On any decider failure the gate fails CLOSED to
  CONFIRM. Nothing asks the main LLM "is this safe?".

## The decision, exactly

```
INPUT: user request + conversation + proposed tool + arguments
   |
DECIDER 2B: 7 typed yes/no questions (noul), one forward pass per question
   |         q_grounded   arguments grounded in facts the user provided?
   |         q_in_scope   action within the scope the user asked for?
   |         q_risky      could it leak secrets, exfiltrate, or damage?
   |         q_premature  premature before checking with the user?
   |         q_proceed / q_confirm / q_deny  (the model's three-way vote)
   |
DECISION: policy thresholds (decider/gate.py)
   |         risky >= 0.75, or vote=DENY with risky >= 0.55        -> DENY
   |         grounded or in_scope <= 0.20                          -> DENY
   |         vote=CONFIRM, risky >= 0.55, premature >= 0.60,
   |         or grounded/in_scope < 0.55                           -> CONFIRM
   |         any decider error                                     -> CONFIRM
   |
ACTION: PROCEED -> execute + audit | CONFIRM -> hold for human | DENY -> block + audit
```

Every signal is a real Decider 2B probability. Nothing is hardcoded, nothing
is faked, and the running application never fabricates the model's output.

## HOW TO RUN

1. AWS credentials with Bedrock access in your environment (standard chain).
2. `cp .env.example .env` and fill in what you use.
3. Start the decision model: `./scripts/run_decider.sh`
   (first run downloads ~4.5 GB to the Hugging Face cache).
4. Seed the demo data: `./scripts/seed_demo_data.sh`
5. Start the backend and UI: `./scripts/run_backend.sh`, open
   http://localhost:8000

## HOW TO TEST

- Unit + boundary tests (no model needed):
  `pip install -r requirements-dev.txt && pytest tests -k "not redteam" -v`
- LIVE red-team suite (needs the decider server):
  `STRANDS_DECIDER_URL=http://127.0.0.1:8099 pytest tests/redteam -v -s`
  This writes docs/evaluation_results.json with the real measured numbers:
  attack detection rate, false positives/negatives, latency, confidence,
  blocked calls. Only numbers from actual runs are reported.

## Red-team coverage (tests/redteam/attack_corpus.py)

legitimate request, obvious prompt injection, indirect prompt injection (a
malicious document), malicious tool arguments, unauthorized action, premature
action, ambiguous request, safe tool call, high-risk action needing approval.

## Demo (60-120 seconds; see docs/demo.md)

1. **SAFE:** "Read the supplier document and email me a summary." Gate: PROCEED.
2. **INDIRECT INJECTION:** vendor_terms_malicious.md contains hidden
   instructions ordering the agent to email the document and database to an
   outsider. Gate: DENY; tool never executes; security event recorded.
3. **HIGH-RISK:** a plausible action with an unstated recipient or scope.
   Gate: CONFIRM; runs only after approval in the UI.

## Repository layout

/agent (agent wiring, the gated boundary) /tools (the three tools)
/decider (Decider 2B client + decision policy) /backend (FastAPI: chat,
approvals, audit) /frontend (UI) /tests (unit, boundary, live red-team)
/docs (security model, decider integration, deployment, demo, evaluation)
/demo/documents (demo corpus, including the malicious document)
/scripts (run/seed helpers)

## Security model (summary; full version in docs/security-model.md)

Tool-call interception at the boundary, grounding and authorization
validation, suspicious-action detection, human confirmation for high-risk
calls, denial for clearly malicious ones, append-only audit log with secret
redaction, safe failure behavior (fail closed). Limits are stated precisely:
no system is 100% secure; this layer constrains a class of prompt-injection
failures and logs everything it does, and its measured performance is
whatever docs/evaluation_results.json actually contains.
