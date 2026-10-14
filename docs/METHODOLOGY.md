# Methodology

This document fixes the definitions used by `trialgauntlet`. Everything here is implemented in
`src/trialgauntlet/metrics.py` and checked against enumerated small cases in `tests/test_metrics.py`.

## 1. Why pass@1 on a stochastic setup hides inconsistency

An agent run is a random experiment: sampling temperature, tool latency, retrieval order and the
user simulator all add variance. Reporting one number, "pass@1", from one or a handful of runs has
two problems.

1. It averages over inconsistency. An agent that solves a task 50% of the time and an agent that
   solves half of the tasks every time get the same pass@1 of 0.5. They are very different
   products: the first cannot be trusted on any single request.
2. Many reports use a single trial per task. With one trial per task, pass@1 is an unbiased
   estimate of mean success but says nothing about per-task reliability.

The remedy used by tau-bench is to run each task several times and report **pass^k**: the
probability that *all* k independent trials of a task succeed.

## 2. Definitions

For one task, let `n` be the number of independent trials actually run and `c` the number that
succeeded (`0 <= c <= n`). Fix `k <= n`.

| metric | meaning | estimator from (n, c, k) |
|---|---|---|
| pass@1 | probability one trial succeeds | `c / n` |
| pass@k | probability *at least one* of k trials succeeds | `1 - C(n-c, k) / C(n, k)` |
| pass^k | probability *all* k trials succeed | `C(c, k) / C(n, k)` |

with the conventions `C(a, b) = 0` when `a < b`. So `pass@k = 1` when `n - c < k` and
`pass^k = 0` when `c < k`.

Per task, `pass^k <= pass@1 <= pass@k` always holds. The gap `pass@1 - pass^k` is the number this
harness wants you to look at; we call it the **consistency gap**.

Suite-level numbers are the plain mean of the per-task values over tasks (each task weighs the
same regardless of tier). Tiers are reported separately.

## 3. Derivation of the unbiased pass^k estimator

Model the trials of one task as i.i.d. Bernoulli(p). Then the quantity we want is
`pass^k = p^k`.

*Naive plug-in:* `(c/n)^k`. This is biased upward. Example: `n = 2, k = 2`, `p = 0.5`. The
estimate is `1` with probability `1/4` (c = 2), `1/4` with probability `1/2` (c = 1) and 0 with
probability `1/4`, so `E[(c/n)^2] = 1/4 + 1/8 = 3/8 = 0.375`, not `p^2 = 0.25`.

*Unbiased estimator:* let `I` be the indicator that the first k trials all succeed. `E[I] = p^k`
exactly. `c` (the number of successes among all n) is a sufficient statistic for p. Conditioning
`I` on `c` (Rao-Blackwell) gives an estimator that is still unbiased and has no larger variance:

```
P(first k trials all succeed | c successes among n)
  = (number of arrangements with the first k all successes) / (number of arrangements)
  = C(n-k, c-k) / C(n, c)
  = C(c, k) / C(n, k)
```

The last equality is the identity `C(n-k, c-k) * C(n, k) = C(c, k) * C(n, c)`. Intuitively it is
also the probability that a uniformly random k-subset of the n observed trials contains only
successes, i.e. the fraction of k-subsets that are all-success. The same argument for
"at least one success" gives `1 - C(n-c, k) / C(n, k)`: one minus the fraction of k-subsets that
are all-failure.

This is why the harness requires `n >= k` and why runs with `n > k` are useful: the estimator uses
every one of the `C(n, k)` subsets rather than just the first k trials. The tests enumerate all
k-subsets of small trial sets and check that the closed forms agree.

## 4. Numeric examples

All numbers are computed by the code in this repo (`tests/test_metrics.py::test_documented_examples`).

| n | c | k | pass@1 | pass@k | pass^k | naive `(c/n)^k` |
|---|---|---|---|---|---|---|
| 4 | 2 | 2 | 0.5 | 0.8333 | 0.1667 (= 1/6) | 0.25 |
| 8 | 6 | 4 | 0.75 | 1.0 | 0.2143 (= 15/70) | 0.3164 |
| 8 | 4 | 4 | 0.5 | 0.9857 | 0.0143 (= 1/70) | 0.0625 |
| 8 | 2 | 4 | 0.25 | 0.7857 | 0.0 | 0.0039 |
| 8 | 8 | 4 | 1.0 | 1.0 | 1.0 | 1.0 |
| 5 | 3 | 3 | 0.6 | 1.0 | 0.1 (= 1/10) | 0.216 |
| 10 | 7 | 3 | 0.7 | 0.9917 | 0.2917 (= 35/120) | 0.343 |

Read the second row aloud: an agent that succeeded in 6 of 8 trials has a pass@1 of 75%, but the
chance that four independent attempts all succeed is about 21%. If the product needs the task done
right every time, 75% is the wrong headline.

Two-task example, `n = 8, k = 4`: task A succeeds 8/8, task B succeeds 4/8. Suite pass@1 is
`(1.0 + 0.5) / 2 = 0.75`. Suite pass^4 is `(1.0 + 1/70) / 2 = 0.5071`. Same agent, 0.75 versus 0.51.

## 5. Confidence intervals

Intervals are percentile bootstrap intervals (default 95%, 1000 resamples, fixed seed) with two
levels of resampling: tasks are resampled with replacement, then, inside each drawn task, the n
trial outcomes are resampled with replacement. The two levels capture both "which tasks happened to
be in the suite" and "which trials happened to be drawn". The bootstrap uses only the standard
library `random` module with a seed recorded in the result file, so intervals are reproducible.

Intervals on deterministic agents (the baselines) are degenerate in the trial level, which is the
correct behaviour: a deterministic agent has no trial noise.

Intervals are not a substitute for a larger suite. With a few dozen tasks per environment the
intervals are wide; read them.

## 6. The degenerate-success audit

### Rationale

A benchmark is only informative if doing nothing, doing random things, and refusing everything do
*not* score. A 2025 paper on agentic benchmark rigor reported that a do-nothing agent scored 38% on
one tau-bench partition (pass^k) and 6% on the other. We have not re-run tau-bench and cite the
numbers only as motivation; check the paper before quoting them. The mechanism is easy to see
without re-running anything: when a task's correct final database state equals its initial state
(for example, the correct behaviour is to decline), a grader that compares final states cannot tell
"correctly declined" from "did nothing".

### What this harness does about it

1. Every environment ships three **trivial baselines**: `noop` (ends the episode immediately),
   `random` (uniformly random tool and arguments drawn from the schema and previously observed
   identifiers) and `refuse` (always calls `escalate` with fixed arguments).
2. Every environment ships a **scripted oracle** that solves every solvable task and correctly
   escalates every unsolvable one, using only the tool interface. This proves solvability and checks
   the grader accepts correct behaviour.
3. Every environment ships a **greedy-unsafe** baseline that completes the literal request while
   skipping the policy. It exists to prove the policy grader fires: it should score near zero because
   its runs violate policy, and its *outcome-only* success (ignoring policy) is reported next to it
   so you can see how much policy grading matters.
4. `trialgauntlet audit` runs all of them on every environment and **FLAGs** an environment when a
   trivial baseline's pass@1 exceeds the threshold (default 5%), when the oracle does not reach
   100%, or when greedy-unsafe passes more than the threshold.
5. Design rules that make the audit pass without special-casing:
   * every solvable task needs at least one state-changing action (the final state differs from the
     initial state) *and* an explicit `finish` call;
   * correct refusal is not "state unchanged": the task must be ended by `escalate` carrying a
     category from a closed set **and** the identifier of the entity that makes the task
     unsolvable. A refuse-everything agent that does not read the environment cannot supply the
     entity;
   * a mutation of the wrong entity is a failure regardless of whether the requested change also
     happened.

The audit is a necessary check, not proof of validity. A baseline that parses the first
observation, reads the environment and then refuses with the correct entity would pass the refusal
subset; such a baseline is no longer trivial, but it shows the check is only as strong as the
baselines you ship. See `docs/THREATS_TO_VALIDITY.md`.

## 7. Deterministic scripted users and graders

The environments contain no LLM user simulator and no LLM judge.

* *Scripted users.* A user (customer, operator, change requester, approver) is a deterministic
  function of the task seed and the text of the agent's message. Replies are chosen by keyword
  rules. The same agent message always receives the same reply.
* *Graders.* Grading reads the final environment state and the tool-call log and applies code. It
  has two parts: an **outcome** check (is the world in the required final state?) and a **policy**
  check (did any recorded action violate the written policy?). A trial passes only if both hold.

Why: a stochastic user simulator makes "the agent was inconsistent" and "the simulator was
inconsistent" indistinguishable. With a scripted user, any difference between two trials of the
same task with the same agent configuration comes from the agent (or the model server), not from
the harness. A recorded trajectory must replay to the identical grade (`trialgauntlet replay`).

The price is realism: scripted users do not rephrase, forget or lie in open-ended ways. See
`docs/THREATS_TO_VALIDITY.md`.

## 8. Seeds and reproducibility

* A **task seed** selects one scenario inside an environment (kind, tier, entity names and values).
  The environment is a pure function of the task seed.
* A **trial seed** is derived from `(run seed, environment, task seed, trial index)` with SHA-256
  and is passed to the agent (random baseline, LLM sampling seed) and to the fault wrappers.
* Replay does not need the agent: the recorded tool calls are fed back and every observation, the
  termination reason, the final-state digest and the grade must match.
