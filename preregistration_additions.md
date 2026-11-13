# Pre-registration additions

## 2026-10-25T00:00:00Z passk-decay proposal:5b8d8980f2826ab7a98f0d3e9a99835a948d6356c2a4d4ab50e66b176ea8845b

**Hypothesis.** For a scripted noisy oracle whose per-trial success probability depends on difficulty tier
(T1 0.95, T2 0.85, T3 0.60), mean pass^8 over tasks exceeds the independence prediction (mean pass@1)^8 by
at least 0.05, while the shipped seeded random-tool baseline has pass^k of 0.0 for every k, so it does not
move the headline table. The noisy oracle is SIMULATED: success is a seeded Bernoulli draw, no environment is
executed and no model is involved.

**Metric.** `/pass_hat_k/8/gap_vs_independence` in `results/31-passk-decay.json`: observed mean pass^8 minus
(mean pass@1)^8, over all tasks of fleet, ledger and config, n=32 trials per task, seed 7.

**Expected.** Positive, at least 0.05 (range 0.05 to 0.3).

**Falsifier.** `gap_vs_independence` at k=8 below 0.05 or negative, or the random baseline showing nonzero
pass^k at any k in 1..8.

**Run.** `python3 scripts/passk_decay.py --seed 7 --n 32 --k-max 8 --out results/31-passk-decay.json`

## 2026-10-25T13:07:49Z chance-floor proposal:757e4abe7aa9ac1264e472c8cc44449a1cd1fed2ce6ad566d6d1013aa750919b

**Hypothesis.** At k=8 the SIMULATED tier-dependent noisy oracle's pass^k exceeds the seeded random-tool
baseline's pass^k by more than 0.10 (n=32 trials per task, fleet, ledger and config pooled, seed 7), i.e. the
chance floor does not move the headline table; the random baseline's pass^8 stays below 0.05.

**Metric.** `/chance_audit/max_gap_over_chance_k8` in `results/32-chance-floor.json`: noisy-oracle mean pass^8
minus random-baseline mean pass^8 over all tasks.

**Expected.** At or above 0.10 (range 0.10 to 1.0).

**Falsifier.** A gap over chance at k=8 below 0.10, or a random-baseline pass^8 of 0.05 or more.

**Run.** `python3 scripts/chance_floor.py --seed 7 --n 32 --k-max 8 --out results/32-chance-floor.json`

## 2026-10-25T21:59:23Z escalate-guess proposal:4381c3d79c920d783e284cba1c0dab496e31c3ca31013e37dc46e395832f99bc

**Hypothesis.** On escalation-required tasks (4 categories per environment, n=32 trials per task, seed 7), a
seeded random-category escalate-guesser has category-only mean pass@8 of at least 0.80 while its category-only
mean pass^8 stays below 0.01, so a hand-off floor inflates pass@k with k and stays invisible in pass^k; under
full grading that also requires the correct blocking entity, its pass@8 stays below 0.30.

**Metric.** `/escalate_guess/category_only/pass_at_k/8` in `results/38-escalate-guess.json`.

**Expected.** Increases with k, at least 0.80 at k=8 (range 0.80 to 1.0).

**Falsifier.** Category-only pass@8 below 0.80, or category-only pass^8 of 0.01 or more, or full-grading pass@8
of 0.30 or more.

**Run.** `python3 scripts/escalate_guess.py --seed 7 --n 32 --k-max 8 --out results/38-escalate-guess.json`

## 2026-10-25T22:09:44Z ci-width proposal:fc93210c1a4b458ca86b28f182915af52a7b0d73730f5335c896f1dcc8f545e9

**Hypothesis.** For the SIMULATED tier-dependent noisy oracle (fleet, ledger and config pooled, seed 7, 1000
task-level bootstrap resamples), the 95% interval width of mean pass^8 at n=8 trials per task is less than 1.25
times the width at n=64, because task sampling rather than trial count dominates the interval; the ratio stays at
or above 1.0.

**Metric.** `/ci_width/ratio_n8_over_n64_k8` in `results/40-ci-width.json`.

**Expected.** Ratio between 1.0 and 1.25.

**Falsifier.** A ratio of 1.25 or more, or below 1.0.

**Run.** `python3 scripts/ci_width.py --seed 7 --k 8 --n-list 8,16,32,64 --boot 1000 --out results/40-ci-width.json`

## 2026-11-11T10:00:29Z heterogeneity-gap proposal:419b1a94be9f9947e5918bd0bdfa34591b8fcb97f26afda735336b7493de91cc

**Hypothesis.** At matched pooled pass@1 on the shipped seeded fleet, ledger and config task sets (seed 7, n=16
trials per task, 1000 task-level bootstrap resamples), the absolute difference between the pass^4 gap versus p^4 of
two SIMULATED generators (iid trials with tier-spread difficulty, and homogeneous sticky Markov trials with rho
calibrated by deterministic grid search) is at most 0.03 while each gap's 95% interval excludes zero, so the gap
column cannot tell heterogeneity from within-task correlation; the lag-1 within-task autocorrelation of trial
outcomes differs between the generators by at least 0.15.

**Metric.** `/heterogeneity_gap/k_4` in `results/91-heterogeneity-gap.json`.

**Expected.** Absolute difference in pass^4 gap between generators is at most 0.03.

**Falsifier.** Absolute pass^4 gap difference above 0.03 after calibration, or either gap interval including zero,
or lag-1 autocorrelation difference below 0.15.

**Run.** `python3 scripts/heterogeneity_gap.py --seed 7 --n 16 --k-max 8 --boot 1000 --out results/91-heterogeneity-gap.json`

## 2026-11-13T11:32:48Z flip-passk-sesoi proposal:b972c8403b8d3f2d79bba9bd04c593e85a2aeff25305ac572e7e677b4bc9ee0b

**Hypothesis.** With a symmetric per-trial outcome flip at the largest of three mock rates applied to the
SIMULATED tier-dependent oracle (n=8 trials per task, 138 task seeds, seed 11), pass^k falls below the flip-free
curve by more than a pre-stated SESOI of 0.05 at some k no larger than 4, and the first-divergence k never
increases as the flip rate grows.

**Metric.** `/flip_passk/k_first_divergent` in `results/150-flip-passk-sesoi-mock.json` (largest flip rate).

**Expected.** k_first_divergent at the largest flip rate is at most 4 (range 1 to 4).

**Falsifier.** At the largest flip rate no k in 1..8 has a pass^k gap to the flip-free curve above 0.05 with k<=4,
or the first-divergence k increases as the flip rate grows.

**Run.** `python3 scripts/flip_passk_sesoi.py --seed 11 --out results/150-flip-passk-sesoi-mock.json`
