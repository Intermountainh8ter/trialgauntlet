#!/usr/bin/env python3
"""Closed-form floor of the seeded random-category escalate-guesser (category-only grading) against a fresh
measurement. Per task q = 1/|categories| if the expected category is in the enum, else 0; pass^k = mean q^k.
Standard library plus the package only."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from escalate_guess import ENVS, curves, outcomes_for  # noqa: E402

from trialgauntlet.agents.baselines import EscalateGuessAgent  # noqa: E402
from trialgauntlet.envs import make_env  # noqa: E402
from trialgauntlet.envs.base import norm  # noqa: E402
from trialgauntlet.harness import evaluate_env  # noqa: E402


def task_hit_probs() -> list[float]:
    """Probability the uniform category guess equals the expected category, per escalate-expected task."""
    qs = []
    for env_name in ENVS:
        env = make_env(env_name)
        for spec in env.task_specs():
            if spec.expect != "escalate":
                continue
            env.reset(spec.seed)
            esc = next(t for t in env.tools() if t.name == "escalate")
            enum = [norm(c) for c in esc.parameters["properties"]["category"]["enum"]]
            expected = env._expected_escalation()
            qs.append(1.0 / len(enum) if expected and norm(expected[0]) in enum else 0.0)
    return qs


def closed_form(qs: list[float], k_max: int) -> dict[str, float]:
    return {str(k): round(sum(q**k for q in qs) / len(qs), 6) for k in range(1, k_max + 1)}


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

    results = []
    for env in ENVS:
        r, _ = evaluate_env(env, EscalateGuessAgent, n=a.n, k=a.k_max, seed=a.seed, n_boot=10)
        results.extend(r)
    cat = outcomes_for(results, True)
    meas = curves(cat, a.k_max, a.seed, a.n_boot)
    qs = task_hit_probs()
    cf = closed_form(qs, a.k_max)
    dev = {k: round(abs(cf[k] - meas["pass_hat_k"][k]), 6) for k in cf}
    lo, hi = meas["pass_hat_k_ci95"]["1"]
    doc = {
        "label": "closed-form vs measured category-only pass^k of the seeded random-category escalate-guesser (no LLM)",
        "config": {"n": a.n, "k_max": a.k_max, "n_boot": a.n_boot, "envs": list(ENVS), "tasks": len(qs)},
        "floor": {
            "closed_form_pass_hat_k": cf,
            "measured_pass_hat_k": meas["pass_hat_k"],
            "abs_deviation": dev,
            "max_abs_deviation_category_only": max(dev.values()),
            "pass_at_1_in_ci95": lo <= cf["1"] <= hi,
            "measured_pass_at_1_ci95": [lo, hi],
        },
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/closed_form_floor.py " + " ".join(argv if argv is not None else sys.argv[1:]),
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
