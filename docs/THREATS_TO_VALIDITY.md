# Threats to validity

What the numbers in this repository can and cannot support. Read this before quoting any of them.

## What has actually been measured

* The built-in **non-LLM** agents (no-op, random-tool, always-refuse, scripted-oracle, greedy-unsafe,
  gullible, oracle-retry) on the three built-in environments. These numbers are real, deterministic and
  reproducible with `scripts/regenerate_results.sh`.
* The adapter and the reporting path against a **mock** server. Those runs are labelled MOCK and say
  nothing about any model.
* **No real LLM has been run.** Every LLM-facing claim in this repository is about the plumbing.

## Construct validity: do the environments measure reliability?

1. **The environments are small.** 42 to 52 tasks each, generated from 11 to 14 scenario kinds with
   3 to 4 variants. Variants change names, ids and numbers, not the structure of the problem. A model that
   learns the 14 templates would score well without being generally reliable. Confidence intervals are
   over tasks and are wide; read them.
2. **Scripted users are unrealistic.** The customer, operator, approver and requester answer by keyword
   rules. They never rephrase, forget, lie, get angry or change their mind, and the same agent message
   always gets the same reply. That is the point (it removes simulator noise from the measurement) and
   also the limit: tau-bench-style user simulation tests dialogue skills this harness does not. A model
   can also pass or fail on the exact phrasing that trips a keyword rule (for example, asking for "the
   card digits" instead of "last 4 digits" still works, but an unusual phrasing may not).
3. **The graders encode one author's policy.** "Correct" means "matches the policy documents in this
   repository as the author wrote them", including judgement calls (a 30 day window, 20000 cents for manager
   approval, `final_sale` never refundable, a capacity floor of 3 web hosts). A reasonable operator could
   disagree with some of them. Policy violations are counted by code the author wrote; a violation the
   author did not think of is invisible, and a rule that is too strict fails a sensible agent.
4. **The oracle and the grader share an author.** The scripted oracle proves each task is solvable *by the
   author's reading of the policy*. It does not prove the policy is the only sensible one, and a grader
   bug that the oracle happens to satisfy would not be caught by the oracle.
5. **The unsolvable subset is large (31 to 36% of tasks)** and the escalation scoring is strict (right
   category and right entity). That is deliberate (it is what kills degenerate baselines) but it means
   escalation behaviour weighs heavily in every score. Slices are reported separately: use them.
6. **Hidden invariants are documented in the repository** (`docs/CHANGE_POLICY.md` inside the `config`
   environment). An agent that never reads the policy fails by design; an agent that reads it does not
   have to *discover* the invariants. This tests diligence, not discovery.

## The audit is only as strong as its baselines

* The audit shows that **these five baselines** do not pass. It does not show that no cheap strategy
  does. A baseline that reads the environment and then refuses with the right category and entity would
  be non-trivial but would pass the escalate subset; one that parses identifiers from the first
  observation and escalates with a fixed category would pass a few percent of `fleet` tasks (one in four
  escalation kinds per category). Neither is included. The `+naive` demo rows show what the audit looks
  like when the grader is the problem; they do not prove the real graders are sound.
* The random baseline draws argument values from identifiers it has already seen. Stronger random policies
  exist. Its 0.7% on `fleet` (3 of 416 trials) is the honest number for this one.
* The threshold (5% on pass@1) is a convention, not a derivation. The README table reports the
  intervals so you can pick your own.
* No iteration on the environments was needed after the first audit run because the design rules were
  chosen in advance with the known failure mode in mind. That is a design claim, not evidence that
  the environments are free of other degenerate strategies.

## Internal validity: is the measurement what it says it is?

* **pass^k assumes independent trials.** With temperature 0 (or a fixed seed on a deterministic server) all
  trials of a task are identical and pass^k equals pass@1: the harness cannot show inconsistency that
  sampling does not produce. Server-side effects (prompt caching, batching, kernel nondeterminism,
  `seed` being ignored by a server) can correlate trials in ways the estimator does not model. The
  adapter passes a different seed per trial, but whether a server honours it is the server's business.
* **Task sampling dominates the intervals.** Intervals come from a cluster bootstrap over tasks. With
  few tasks they are wide and not exactly 95%. They do not cover differences between server builds,
  quantizations or chat templates, which can be larger than the effect you want to measure.
* **Bootstrap history.** An earlier two-level bootstrap was biased for pass^k and was replaced (see
  `docs/METHODOLOGY.md` section 5). The test suite now asserts that the interval contains the point
  estimate; that is a regression guard, not a proof of coverage.
* **Budgets change results.** A trial that exceeds the step, token or time budget is a failure even if the
  state would have been correct a step later. Time budgets are not replayable. Default step budgets were set
  by the author (30 to 40) and were not tuned against any model.
* **The mock server tests plumbing only.** Its oracle mode replays the scripted oracle over the transcript;
  a 100% score through it says the HTTP, parsing and history handling work, not that any model can do the
  task. Its flaky mode creates a pass@1 versus pass^k gap by construction.
* **Python versions.** The full test suite (which includes a byte-for-byte comparison of the committed result
  files with fresh output) passed on Python 3.10.20, 3.11.17, 3.12.3 and 3.13.16 on one Linux machine. Other
  platforms were not tried.

## Injection and fault suites

* The injected text is three fixed templates, not adaptive attacks. A low attack success rate on them is
  weak evidence. Exposure matters: an agent that never reads a poisoned tool has ASR 0 for free.
* The attacker's goal is always a single tool call. Multi-step or state-conditional attacks are not covered.
* Faults are independent per call, capped at two in a row, and the built-in tools are retry-safe by design
  (an exact repeat of the previous successful state-changing call is ignored). Real tools are often not.
  The scripted agents that demonstrate recovery are written by the author and say nothing about models.

## External validity

* Three environments in three domains do not make a general agent benchmark, and this repository does not
  claim to be one. The field already has tau-bench, ReliabilityBench, Agent Reliability Lab and others; the
  contribution here is the audit-first design and being tiny, deterministic and dependency-free.
* The motivating published finding (a do-nothing agent scoring well on a tau-bench partition) is cited
  from memory of the abstract and has not been re-run here. The `+naive` variants illustrate the mechanism
  on this repository's own tasks; they do not reproduce that paper's numbers.
* Everything is synthetic. There is no contamination concern in the usual sense (tasks are generated from
  seeds), but the generators are public: a model trained on this repository could memorise them.

## Things that were not done

* No real LLM result exists. The README says so and `trialgauntlet report` prints "LLM results: NOT YET RUN"
  until a non-mock result file for a model is present.
* The Windows PowerShell commands in the README were written from llama.cpp documentation and the
  author's setup notes; they were not executed on Windows or against Qwen3-Coder during development.
* The Dockerfile was written but its build is not part of the test suite.
* No human validation of the graders, no inter-annotator check, no second implementation of the policies.
