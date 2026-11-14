#!/usr/bin/env python3
"""Bootstrap-scheme audit: 95% interval widths of the SIMULATED noisy oracle's mean pass^k under task resampling,
within-task rollout resampling and a hierarchical (both) bootstrap. Standard library plus the package only."""

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

from trialgauntlet.metrics import TaskOutcome, mean, pass_hat_k  # noqa: E402

_spec = importlib.util.spec_from_file_location("passk_decay", HERE / "passk_decay.py")
pk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pk)


def _resample_c(rng: random.Random, n: int, c: int) -> int:
    """Resample n rollouts with replacement from c successes and n-c failures."""
    return sum(1 for _ in range(n) if rng.randrange(n) < c)


def scheme_width(outcomes: list[TaskOutcome], k: int, seed: int, n_boot: int, scheme: str) -> dict:
    if scheme not in ("task", "rollout", "hierarchical"):
        raise ValueError(scheme)
    rng = random.Random(seed)
    m = len(outcomes)
    vals = [pass_hat_k(x.n, x.c, k) for x in outcomes]
    boots = []
    for _ in range(n_boot):
        idx = [rng.randrange(m) if scheme != "rollout" else i for i in range(m)]
        if scheme == "task":
            boots.append(mean([vals[i] for i in idx]))
        else:
            boots.append(mean([pass_hat_k(outcomes[i].n, _resample_c(rng, outcomes[i].n, outcomes[i].c), k)
                               for i in idx]))
    boots.sort()
    lo, hi = boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
    return {"mean_pass_hat": round(mean(vals), 6), "ci95": [round(lo, 6), round(hi, 6)],
            "width": round(hi - lo, 6)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.n < a.k:
        ap.error("n must be at least k")
    t0 = time.time()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pk.simulate_outcomes(a.seed, a.n)
    by = {s: scheme_width(out, a.k, a.seed, a.boot, s) for s in ("task", "rollout", "hierarchical")}
    rw = by["rollout"]["width"]
    ratio = round(by["task"]["width"] / rw, 6) if rw > 0 else None
    doc = {
        "label": "SIMULATED noisy oracle (seeded Bernoulli by tier); pass^k interval width by bootstrap scheme",
        "config": {"k": a.k, "n": a.n, "boot": a.boot, "tier_p": pk.TIER_P, "envs": list(pk.ENVS),
                   "tasks": len(out)},
        "schemes": by,
        "interval_width_ratio": {f"task_over_rollout_k{a.k}": ratio,
                                 f"hierarchical_over_task_k{a.k}":
                                 round(by["hierarchical"]["width"] / by["task"]["width"], 6)
                                 if by["task"]["width"] > 0 else None},
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/boot_scheme.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "hardware": f"{platform.machine()} {platform.system()} python {platform.python_version()}, cpu only",
            "wall_s": round(time.time() - t0, 3),
            "data_sources": [],
        },
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
