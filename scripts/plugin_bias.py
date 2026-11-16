#!/usr/bin/env python3
"""Plug-in bias audit: SIMULATED tier-dependent oracle; compares the naive (c/n)^k with the unbiased
C(c,k)/C(n,k) against the known per-task p^k across trials-per-task n. Standard library plus the package only."""

from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from trialgauntlet.envs import make_env  # noqa: E402
from trialgauntlet.metrics import mean, pass_hat_k  # noqa: E402

ENVS = ("fleet", "ledger", "config")
TIER_P = {"T1": 0.95, "T2": 0.85, "T3": 0.60}
NS = (4, 8, 16, 32)


def task_ps() -> list[float]:
    return [TIER_P[t.tier] for env in ENVS for t in make_env(env).task_specs()]


def bias_for_n(ps: list[float], n: int, k: int, reps: int, seed: int) -> dict:
    """Mean (estimate - p^k) over reps replications of the whole task set, for both estimators."""
    rng = random.Random(seed * 1000 + n)
    truth = mean([p**k for p in ps])
    plug, unb = [], []
    for _ in range(reps):
        cs = [sum(1 for _ in range(n) if rng.random() < p) for p in ps]
        plug.append(mean([(c / n) ** k for c in cs]))
        unb.append(mean([pass_hat_k(n, c, k) for c in cs]))
    return {"true_mean": round(truth, 6),
            "plugin_bias": round(mean(plug) - truth, 6),
            "unbiased_error": round(mean(unb) - truth, 6)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ps = task_ps()
    by_n = {str(n): bias_for_n(ps, n, a.k, a.reps, a.seed) for n in NS if n >= a.k}
    plug = [by_n[str(n)]["plugin_bias"] for n in NS if n >= a.k]
    doc = {
        "label": "SIMULATED tier-dependent oracle (seeded Bernoulli); plug-in vs unbiased pass^k estimator bias",
        "config": {"k": a.k, "reps": a.reps, "ns": [n for n in NS if n >= a.k], "tier_p": TIER_P,
                   "envs": list(ENVS), "tasks": len(ps)},
        "by_n": by_n,
        "plugin_bias": {f"n{n}_k{a.k}": by_n[str(n)]["plugin_bias"] for n in NS if n >= a.k},
        "unbiased_error": {f"n{n}_k{a.k}": by_n[str(n)]["unbiased_error"] for n in NS if n >= a.k},
        "plugin_bias_monotone_decreasing": all(x > y for x, y in zip(plug, plug[1:])),
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/plugin_bias.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "hardware": f"{platform.machine()} {platform.system()} python {platform.python_version()}, cpu only",
            "wall_s": round(time.time() - t0, 3),
            "data_sources": [{"url": "https://arxiv.org/abs/2406.12045",
                              "license": "arXiv paper, definition of pass^k only; outcomes are simulated"}],
        },
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
