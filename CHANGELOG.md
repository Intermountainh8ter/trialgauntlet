# Changelog

## 0.1.0

First release. Everything below is verified by the test suite; no real LLM has been run.

### Core
* `Environment` and `Agent` protocols, a seeded and budgeted trial runner (steps, tokens, wall clock),
  JSONL trajectories with atomic writes, resumable suites, and `trialgauntlet replay` which re-runs a
  recorded trajectory and requires every observation, the termination reason, the final-state digest and
  the grade to be identical.
* Metrics: pass@1, pass@k and pass^k with the unbiased estimator `C(c,k)/C(n,k)` (checked against
  enumerated k-subsets and exact binomial expectations), per-task aggregation, cluster-bootstrap
  confidence intervals, token, latency, step, cost, tool-misuse and policy-violation counts.

### Environments (deterministic, seeded, scripted users, graded on final state and policy)
* `fleet`: 52 tasks, `ledger`: 42 tasks, `config`: 44 tasks; three tiers each and an unsolvable or
  ambiguous subset where the correct behaviour is `escalate` with the right category and entity.
* Per environment: a scripted oracle (100% on every task) and a greedy-unsafe agent (never passes).

### Audit
* `trialgauntlet audit`: no-op, random-tool, always-refuse, scripted-oracle and greedy-unsafe on every
  environment; FLAG when a trivial baseline exceeds a threshold (default 5%), when the oracle is below
  100%, or when the shortcut agent passes. Exit status 1 on a flag. `<env>+naive` demonstration graders.
* Result: all trivial baselines at or below 0.7% pass@1 on every environment.

### Suites
* Prompt-injection wrapper (`+inject=instruction|fake_system|exfil`) graded on tool calls with exposure
  and utility under attack; fault wrapper (`+fault=transient|timeout|malformed|lost_response|mixed[:rate]`)
  with recovery metrics; `gullible` and `oracle-retry` agents prove both graders fire.

### LLM adapter and reporting
* OpenAI-compatible tool-calling agent over `urllib` (retries with backoff, per-trial seed, temperature,
  usage and latency capture, strict handling of malformed and text-mode tool calls); scripted mock server
  (runs labelled MOCK); `trialgauntlet doctor`; `run --agent llm`.
* `report` renders markdown and two hand-written SVG charts from `results/*.json` and refuses when there
  are none; `leaderboard` builds and validates a leaderboard JSON (`docs/leaderboard.schema.json`).

### Fixed during development (kept visible on purpose)
* The first bootstrap resampled trials inside tasks as well. For pass^k it was biased: a mock run showed
  pass@k = 99.0% with an interval of [94.2%, 99.0%]. Replaced by a task-level cluster bootstrap and a
  regression test.
* A retry after a lost response was punished as collateral damage by the `fleet` grader. Exact repeats of
  the previous successful state-changing call are now ignored by every environment.
