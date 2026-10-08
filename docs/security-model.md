# Security model

## Threat model
An agent driven by untrusted content (documents, emails, pages) may propose
tool calls that serve an attacker: exfiltration, unauthorized data access,
email to unintended recipients, premature or ambiguous actions.

## Controls
1. **Boundary interception.** The agent's tool registry contains only
   `GatedTool` wrappers (agent/gated_tools.py). The real function bodies are
   unreachable by the LLM's tool choice; DENY raises before execution.
2. **Grounding validation.** Decider 2B answers whether the call's arguments
   trace to facts the user provided.
3. **Authorization/scope validation.** Whether the action stays in the scope
   the user asked for.
4. **Risk classification.** Whether the call could leak secrets, exfiltrate,
   or damage anything.
5. **Prematurity detection.** Whether it would be premature before checking
   with the user.
6. **Human-in-the-loop.** CONFIRM parks the call in an approval queue; the
   tool executes only after a human approves it (and is audited then too).
7. **Audit logging.** Every intercepted call produces an append-only record
   (timestamp, tool, arguments, decision, confidence, reason, execution
   status) with secret redaction before writing.
8. **Fail-closed failure behavior.** Decider unreachable or malformed
   response: CONFIRM. A human decides when the decision layer is down.
9. **Secrets hygiene.** Credentials via environment variables only;
   `.env` and credential files are gitignored; `.env.example` documents them.
   The audit log redacts key-shaped strings before writing.

## Layered defenses inside the tools themselves
Boundary enforcement does not replace defense in depth: `read_document`
refuses paths outside DOCUMENTS_DIR, `database_query` runs only SELECT
statements, and `send_email` in demo mode writes to an outbox rather than
sending.

## Precise limits (stated, not claimed away)
No layer is 100% secure. This constrains the class of failures above and
logs every decision; measured performance is whatever docs/evaluation_results.json
contains from actual runs. Adversaries may find new classes of attacks; the
question set and thresholds are configuration, so they can be tightened.
