# Test / evaluation methodology

- **Unit + boundary tests** (no model needed): the decision policy's
  threshold mapping, the tool boundary (a denied call must never reach the
  function body: a spy proves it), approval queue lifecycle, audit redaction.
  Run: `pytest tests -k "not redteam" -v`
- **LIVE red-team suite** (needs the decider server): 9 corpus cases through
  the real gate. Metrics computed from the actual runs and written to
  docs/evaluation_results.json: attack detection rate, false positives
  (legitimate denied), false negatives (attacks that passed), average
  decision latency, per-case Decider signals and confidence, blocked calls.
- **No invented numbers.** Only docs/evaluation_results.json and test output
  are evidence; if no live run has happened yet, no performance claims exist.
