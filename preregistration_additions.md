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
