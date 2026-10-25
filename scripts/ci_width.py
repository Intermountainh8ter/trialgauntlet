#!/usr/bin/env python3
"""CI-width audit: task-bootstrap 95% interval width of the SIMULATED noisy oracle's mean pass^k as the number
of trials per task n grows. Standard library plus the package only."""

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


def ci_width(outcomes: list[TaskOutcome], k: int, seed: int, n_boot: int) -> dict:
    """Mean pass^k with a percentile task-bootstrap 95% interval and its width."""
    rng = random.Random(seed)
    vals = [pass_hat_k(x.n, x.c, k) for x in outcomes]
    m = len(vals)
    boots = sorted(mean([vals[rng.randrange(m)] for _ in range(m)]) for _ in range(n_boot))
    lo, hi = boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
    return {"mean_pass_hat": round(mean(vals), 6), "ci95": [round(lo, 6), round(hi, 6)],
            "width": round(hi - lo, 6)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--n-list", default="8,16,32,64")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ns = [int(x) for x in a.n_list.split(",")]
    if min(ns) < a.k:
        ap.error("every n must be at least k")
    t0 = time.time()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    by_n = {}
    for n in ns:
        out = pk.simulate_outcomes(a.seed, n)
        by_n[str(n)] = ci_width(out, a.k, a.seed, a.boot)
    widths = {n: v["width"] for n, v in by_n.items()}
    ratio = None
    if "8" in widths and "64" in widths and widths["64"] > 0:
        ratio = round(widths["8"] / widths["64"], 6)

    doc = {
        "label": "SIMULATED noisy oracle (seeded Bernoulli by tier); task-level bootstrap interval width vs n",
        "config": {"k": a.k, "n_list": ns, "boot": a.boot, "tier_p": pk.TIER_P, "envs": list(pk.ENVS),
                   "tasks": len(pk.simulate_outcomes(a.seed, ns[0]))},
        "ci_width": {"by_n": by_n, f"ratio_n8_over_n64_k{a.k}": ratio},
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/ci_width.py " + " ".join(argv if argv is not None else sys.argv[1:]),
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
