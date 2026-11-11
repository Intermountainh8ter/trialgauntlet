#!/usr/bin/env python3
"""Heterogeneity-gap audit: can the pass^k gap versus p^k tell tier-spread difficulty (iid trials) from within-task
correlation (homogeneous sticky Markov trials) at matched pooled pass@1? All outcomes are SIMULATED. Standard
library plus the package only."""

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

from trialgauntlet.metrics import mean, pass_hat_k  # noqa: E402

_spec = importlib.util.spec_from_file_location("passk_decay", HERE / "passk_decay.py")
pk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pk)

CAL_SEED_OFFSET = 1000
GRID = [i / 100 for i in range(0, 100)]


def task_tiers() -> list[str]:
    return [t.tier for env in pk.ENVS for t in pk.make_env(env).task_specs()]


def gen_iid(tiers: list[str], n: int, rng: random.Random) -> list[list[int]]:
    return [[1 if rng.random() < pk.TIER_P[t] else 0 for _ in range(n)] for t in tiers]


def gen_markov(m: int, n: int, p: float, rho: float, rng: random.Random) -> list[list[int]]:
    """Stationary two-state chain with marginal p and lag-1 correlation rho."""
    p11, p01 = p + rho * (1 - p), p * (1 - rho)
    rows = []
    for _ in range(m):
        x = 1 if rng.random() < p else 0
        row = [x]
        for _ in range(n - 1):
            x = 1 if rng.random() < (p11 if x else p01) else 0
            row.append(x)
        rows.append(row)
    return rows


def pooled_p1(rows: list[list[int]]) -> float:
    return mean([sum(r) / len(r) for r in rows])


def mean_pass_hat(rows: list[list[int]], k: int) -> float:
    return mean([pass_hat_k(len(r), sum(r), k) for r in rows])


def gap(rows: list[list[int]], k: int) -> float:
    return mean_pass_hat(rows, k) - pooled_p1(rows) ** k


def lag1_autocorr(rows: list[list[int]]) -> float:
    """Pearson correlation of consecutive trials after centring each task on its own mean."""
    xs, ys = [], []
    for r in rows:
        mu = sum(r) / len(r)
        for a, b in zip(r, r[1:]):
            xs.append(a - mu)
            ys.append(b - mu)
    sx = sum(v * v for v in xs)
    sy = sum(v * v for v in ys)
    if sx == 0 or sy == 0:
        return 0.0
    return sum(a * b for a, b in zip(xs, ys)) / (sx * sy) ** 0.5


def gap_ci(rows: list[list[int]], k: int, seed: int, n_boot: int) -> list[float]:
    rng = random.Random(seed)
    m = len(rows)
    boots = sorted(gap([rows[rng.randrange(m)] for _ in range(m)], k) for _ in range(n_boot))
    return [round(boots[int(0.025 * n_boot)], 6), round(boots[int(0.975 * n_boot) - 1], 6)]


def calibrate_rho(m: int, n: int, p: float, target: float, k: int, seed: int) -> float:
    """Grid-search rho so the Markov generator's mean pass^k matches the target (fixed calibration seed)."""
    best, best_err = 0.0, float("inf")
    for rho in GRID:
        rows = gen_markov(m, n, p, rho, random.Random(seed + CAL_SEED_OFFSET))
        err = abs(mean_pass_hat(rows, k) - target)
        if err < best_err:
            best, best_err = rho, err
    return best


def run(seed: int, n: int, k_max: int, n_boot: int, k_cal: int = 4) -> dict:
    tiers = task_tiers()
    m = len(tiers)
    het = gen_iid(tiers, n, random.Random(seed))
    p = pooled_p1(het)
    rho = calibrate_rho(m, n, p, mean_pass_hat(het, k_cal), k_cal, seed)
    hom = gen_markov(m, n, p, rho, random.Random(seed + 1))
    out = {}
    for k in range(1, k_max + 1):
        gh, gm = gap(het, k), gap(hom, k)
        out[f"k_{k}"] = round(abs(gh - gm), 6)
    detail = {}
    for name, rows in (("iid_tier_spread", het), ("sticky_markov", hom)):
        detail[name] = {
            "pooled_pass1": round(pooled_p1(rows), 6),
            "lag1_autocorr": round(lag1_autocorr(rows), 6),
            "by_k": {str(k): {"pass_hat": round(mean_pass_hat(rows, k), 6),
                              "p_pow_k": round(pooled_p1(rows) ** k, 6),
                              "gap": round(gap(rows, k), 6),
                              "gap_ci95": gap_ci(rows, k, seed, n_boot)} for k in range(1, k_max + 1)},
        }
    return {"heterogeneity_gap": out, "generators": detail, "calibrated_rho": rho,
            "lag1_autocorr_abs_diff": round(abs(detail["iid_tier_spread"]["lag1_autocorr"]
                                                - detail["sticky_markov"]["lag1_autocorr"]), 6),
            "tasks": m}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--k-max", type=int, default=8)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.n < a.k_max:
        ap.error("n must be at least k-max")
    t0 = time.time()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = run(a.seed, a.n, a.k_max, a.boot)
    doc = {
        "label": "SIMULATED: iid tier-spread trials vs homogeneous sticky Markov trials at matched pooled pass@1",
        "config": {"n": a.n, "k_max": a.k_max, "boot": a.boot, "k_calibrated": 4, "tier_p": pk.TIER_P,
                   "envs": list(pk.ENVS)},
        **res,
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/heterogeneity_gap.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "hardware": f"{platform.machine()} {platform.system()} python {platform.python_version()}, cpu only",
            "wall_s": round(time.time() - t0, 3),
            "data_sources": [{"url": "https://github.com/sierra-research/tau-bench",
                              "license": "MIT (concept reference only; no data used, SIMULATED outcomes)"}],
        },
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
