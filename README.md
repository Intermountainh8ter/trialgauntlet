# trialgauntlet

A small agent *reliability* harness. Most agent evaluations report pass@1 on a stochastic setup,
which hides inconsistency. This harness reports **pass^k** (all k independent trials succeed) next
to **pass@k**, runs a **degenerate-success audit** (do-nothing, random and refuse-everything
baselines must not score), uses **deterministic scripted users and deterministic graders**, and
ships injection and fault-injection suites (phase 5).

It is deliberately narrow, tiny, deterministic and dependency-free (Python >= 3.10, standard library
only). It is not a general agent benchmark. See `docs/THREATS_TO_VALIDITY.md` (coming with the
docs phase) and `docs/METHODOLOGY.md` for definitions and derivations.

**LLM results: NOT YET RUN.** No result file for a real model exists in this repository. Everything
below is for the built-in non-LLM baseline agents, which are real and reproducible.

## Environments

| env | tasks | what it is |
|---|---|---|
| `fleet` | 52 | triage faults on a simulated bare-metal fleet; destructive actions need approval; graded on fleet state and policy |
| `ledger` | 42 | refund/ledger desk with a written policy, a database and a scripted customer; graded on the final ledger and policy |
| `config` | 44 | multi-file config change with hidden cross-file invariants; graded on file contents and change policy |

Each has three difficulty tiers and an unsolvable/ambiguous subset (the correct behaviour is to
`escalate` with the right category and entity). Details: `docs/ENVIRONMENTS.md`.

## The degenerate-success audit (real output)

Command (about five seconds, no network, no API key):

```
trialgauntlet audit --out-dir results --format markdown
```

`n=8` trials per task, `k=4`, threshold 5% on pass@1. `outcome-only` ignores policy violations;
the gap to `pass@1` is how much the policy grader matters.

| env | agent | pass@1 | 95% CI | pass@4 | pass^4 | outcome-only | verdict |
|---|---|---|---|---|---|---|---|
| fleet | no-op | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| fleet | random-tool | 0.7% | 0.0-2.2% | 2.9% | 0.0% | 1.9% | ok |
| fleet | always-refuse | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| fleet | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| fleet | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 61.5% | ok: shortcut caught |
| ledger | no-op | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| ledger | random-tool | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| ledger | always-refuse | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| ledger | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| ledger | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 50.0% | ok: shortcut caught |
| config | no-op | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| config | random-tool | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| config | always-refuse | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| config | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| config | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 18.2% | ok: shortcut caught |

Honest reading of that table:

* No environment needed to be iterated after the first audit run. The design rules that make the
  audit pass were chosen up front (every solvable task needs a state change and an explicit `finish`;
  a refusal only counts if it names the right category **and** the blocking entity).
* `random-tool` is not exactly zero on `fleet` (0.7%, 3 of 416 trials: two lucky `clock_drift`
  repairs and one correct one-step escalation). It is far below the 5% threshold.
* The scripted oracle solves all 138 tasks. `greedy-unsafe` reaches the right outcome on 61.5% /
  50.0% / 18.2% of the tasks but never passes, because its shortcuts violate the written policy.
* The audit is only as strong as the baselines you ship. A baseline that reads the environment and
  then refuses with the right entity is not trivial and is not included.

What a degenerate benchmark looks like: the same baselines against a deliberately naive grader that
passes unsolvable tasks when the final state is unchanged (`<env>+naive`; not used anywhere else):

| env | agent | pass@1 | 95% CI | pass@4 | pass^4 | outcome-only | verdict |
|---|---|---|---|---|---|---|---|
| fleet+naive | no-op | 30.8% | 19.2-44.2% | 30.8% | 30.8% | 30.8% | FLAG: trivial baseline exceeds 5.0% |
| fleet+naive | random-tool | 16.1% | 8.7-23.8% | 29.9% | 3.4% | 23.6% | FLAG: trivial baseline exceeds 5.0% |
| fleet+naive | always-refuse | 30.8% | 19.2-44.2% | 30.8% | 30.8% | 30.8% | FLAG: trivial baseline exceeds 5.0% |
| fleet+naive | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| fleet+naive | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 61.5% | ok: shortcut caught |
| ledger+naive | no-op | 35.7% | 21.4-50.0% | 35.7% | 35.7% | 35.7% | FLAG: trivial baseline exceeds 5.0% |
| ledger+naive | random-tool | 26.8% | 14.9-38.1% | 35.5% | 11.9% | 35.7% | FLAG: trivial baseline exceeds 5.0% |
| ledger+naive | always-refuse | 35.7% | 21.4-50.0% | 35.7% | 35.7% | 35.7% | FLAG: trivial baseline exceeds 5.0% |
| ledger+naive | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| ledger+naive | greedy-unsafe | 7.1% | 0.0-14.3% | 7.1% | 7.1% | 57.1% | FLAG: policy grader accepted a shortcut |
| config+naive | no-op | 36.4% | 22.7-50.0% | 36.4% | 36.4% | 36.4% | FLAG: trivial baseline exceeds 5.0% |
| config+naive | random-tool | 26.7% | 16.5-37.8% | 36.3% | 10.0% | 36.4% | FLAG: trivial baseline exceeds 5.0% |
| config+naive | always-refuse | 36.4% | 22.7-50.0% | 36.4% | 36.4% | 36.4% | FLAG: trivial baseline exceeds 5.0% |
| config+naive | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| config+naive | greedy-unsafe | 9.1% | 2.3-18.2% | 9.1% | 9.1% | 27.3% | FLAG: policy grader accepted a shortcut |

The do-nothing agent scores {30.8, 35.7, 36.4}% on the naive variants, 0% on the real graders.
This illustrates the mechanism behind a published finding about do-nothing agents on a tau-bench
partition; it does not reproduce that paper's numbers, and we have not re-run tau-bench.

Result files (`results/baseline-*.json`) are byte-identical on regeneration, and were identical on
Python 3.11, 3.12 and 3.13.

## Quickstart

```
pip install -e ".[dev]"
trialgauntlet list
trialgauntlet audit
trialgauntlet run --agent oracle --env fleet --n 4 --k 2 --run-dir runs/oracle
trialgauntlet replay runs/oracle
```

## Metrics

pass@1 = `c/n`; pass@k = `1 - C(n-c,k)/C(n,k)`; **pass^k = `C(c,k)/C(n,k)`** (unbiased for `p^k`,
derivation and numeric examples in `docs/METHODOLOGY.md`). Suite numbers are means over tasks, with
two-level bootstrap confidence intervals.
