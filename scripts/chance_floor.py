#!/usr/bin/env python3
"""Chance-floor audit: per k, the SIMULATED noisy oracle's pass^k minus the shipped seeded random-tool
baseline's pass^k, with task-level bootstrap intervals. Standard library plus the package only."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from trialgauntlet.agents.registry import make_baseline  # noqa: E402
from trialgauntlet.harness import evaluate_env  # noqa: E402
from trialgauntlet.metrics import TaskOutcome, mean, pass_hat_k, tally  # noqa: E402

_spec = importlib.util.spec_from_file_location("passk_decay", HERE / "passk_decay.py")
pk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pk)


def gap_curve(oracle: list[TaskOutcome], rand: list[TaskOutcome], k_max: int, seed: int, n_boot: int) -> dict:
    """Per k: oracle pass^k, random pass^k, the difference and a task-level bootstrap CI of the difference
    (tasks resampled independently within each arm)."""
    rng = random.Random(seed)
    draws = [
        ([oracle[rng.randrange(len(oracle))] for _ in oracle], [rand[rng.randrange(len(rand))] for _ in rand])
        for _ in range(n_boot)
    ]
    res = {}
    for k in range(1, k_max + 1):
        o = mean([pass_hat_k(x.n, x.c, k) for x in oracle])
        r = mean([pass_hat_k(x.n, x.c, k) for x in rand])
        gaps = sorted(
            mean([pass_hat_k(x.n, x.c, k) for x in a]) - mean([pass_hat_k(x.n, x.c, k) for x in b])
            for a, b in draws
        )
        res[str(k)] = {
            "oracle_pass_hat": round(o, 6),
            "random_pass_hat": round(r, 6),
            "gap_over_chance": round(o - r, 6),
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

    oracle = pk.simulate_outcomes(a.seed, a.n)
    rand: list[TaskOutcome] = []
    for env in pk.ENVS:
        results, _ = evaluate_env(env, make_baseline("random", env), n=a.n, k=a.k_max, seed=a.seed, n_boot=10)
        rand.extend(tally(results))
    curve = gap_curve(oracle, rand, a.k_max, a.seed, a.n_boot)
    last = curve[str(a.k_max)]
    audit = {f"max_gap_over_chance_k{a.k_max}": last["gap_over_chance"]}
    audit[f"random_pass_hat_k{a.k_max}"] = last["random_pass_hat"]
    audit["curve"] = curve

    doc = {
        "label": "SIMULATED noisy oracle (seeded Bernoulli by tier) minus the real seeded random-tool baseline",
        "config": {"n": a.n, "k_max": a.k_max, "n_boot": a.n_boot, "tier_p": pk.TIER_P,
                   "envs": list(pk.ENVS), "tasks": len(oracle)},
        "chance_audit": audit,
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/chance_floor.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "hardware": f"{platform.machine()} {platform.system()} python {platform.python_version()}, cpu only",
            "wall_s": round(time.time() - t0, 3),
            "data_sources": [
                {"url": "https://arxiv.org/pdf/2406.12045",
                 "license": "arXiv preprint, definition of pass^k only; no data used"}
            ],
        },
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
