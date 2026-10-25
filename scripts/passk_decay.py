#!/usr/bin/env python3
"""pass^k decay versus the independence prediction p^k, for a SIMULATED tier-dependent noisy oracle and
the shipped seeded random-tool baseline. Standard library plus the trialgauntlet package only."""

from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trialgauntlet.agents.registry import make_baseline  # noqa: E402
from trialgauntlet.envs import make_env  # noqa: E402
from trialgauntlet.harness import evaluate_env  # noqa: E402
from trialgauntlet.metrics import TaskOutcome, mean, pass_hat_k  # noqa: E402

ENVS = ("fleet", "ledger", "config")
TIER_P = {"T1": 0.95, "T2": 0.85, "T3": 0.60}


def simulate_outcomes(seed: int, n: int, tier_p: dict[str, float] = TIER_P) -> list[TaskOutcome]:
    """Seeded Bernoulli trials per task; nothing is executed."""
    rng = random.Random(seed)
    out = []
    for env in ENVS:
        for t in make_env(env).task_specs():
            c = sum(1 for _ in range(n) if rng.random() < tier_p[t.tier])
            out.append(TaskOutcome(env, t.seed, t.tier, t.expect, t.kind, n, c, c))
    return out


def curve(outcomes: list[TaskOutcome], k_max: int, seed: int, n_boot: int) -> dict[str, dict]:
    """Per k: observed pass^k, (mean pass@1)^k, their gap and a task-level bootstrap CI of the gap."""
    p1 = mean([o.c / o.n for o in outcomes])
    rng = random.Random(seed)
    m = len(outcomes)
    draws = [[outcomes[rng.randrange(m)] for _ in range(m)] for _ in range(n_boot)]
    res = {}
    for k in range(1, k_max + 1):
        obs = mean([pass_hat_k(o.n, o.c, k) for o in outcomes])
        gaps = []
        for d in draws:
            q = mean([o.c / o.n for o in d])
            gaps.append(mean([pass_hat_k(o.n, o.c, k) for o in d]) - q**k)
        gaps.sort()
        res[str(k)] = {
            "pass_hat": round(obs, 6),
            "independence": round(p1**k, 6),
            "gap_vs_independence": round(obs - p1**k, 6),
            "gap_ci95": [round(gaps[int(0.025 * n_boot)], 6), round(gaps[int(0.975 * n_boot) - 1], 6)],
        }
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=32)
    ap.add_argument("--k-max", type=int, default=8)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.k_max > a.n:
        ap.error("k-max must not exceed n")
    t0 = time.time()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sim = simulate_outcomes(a.seed, a.n)
    sim_curve = curve(sim, a.k_max, a.seed, a.n_boot)

    rand_outcomes: list[TaskOutcome] = []
    from trialgauntlet.metrics import tally

    for env in ENVS:
        results, _ = evaluate_env(env, make_baseline("random", env), n=a.n, k=a.k_max, seed=a.seed, n_boot=10)
        rand_outcomes.extend(tally(results))
    rand_curve = curve(rand_outcomes, a.k_max, a.seed, a.n_boot)

    doc = {
        "label": "SIMULATED noisy oracle (seeded Bernoulli by tier) plus the real seeded random-tool baseline",
        "config": {
            "n": a.n,
            "k_max": a.k_max,
            "n_boot": a.n_boot,
            "tier_p": TIER_P,
            "envs": list(ENVS),
            "tasks": len(sim),
        },
        "pass_hat_k": sim_curve,
        "random_baseline_pass_hat_k": rand_curve,
        "random_baseline_nonzero_k": [int(k) for k, v in rand_curve.items() if v["pass_hat"] > 0],
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/passk_decay.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "hardware": f"{platform.machine()} {platform.system()} python {platform.python_version()}, cpu only",
            "wall_s": round(time.time() - t0, 3),
            "data_sources": [
                {
                    "url": "https://arxiv.org/pdf/2406.12045",
                    "license": "arXiv preprint, definition of pass^k only; no data used",
                }
            ],
        },
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
