#!/usr/bin/env python3
"""Escalate-guess floor: pass@k and pass^k of a seeded random-category escalate-guesser on the
escalation-required tasks, under category-only and full (category plus blocking entity) grading, with
task-level bootstrap intervals. Standard library plus the package only."""

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

from trialgauntlet.agents.baselines import EscalateGuessAgent  # noqa: E402
from trialgauntlet.harness import evaluate_env  # noqa: E402
from trialgauntlet.metrics import TaskOutcome, mean, pass_at_k, pass_hat_k  # noqa: E402

ENVS = ("fleet", "ledger", "config")
# TrialResult.reason values that show the escalation carried the expected category.
_CATEGORY_WRONG = "wrong escalation category"


def outcomes_for(results, category_only: bool) -> list[TaskOutcome]:
    """Per-task tallies over escalate-expected tasks; category-only counts a right category as success."""
    groups: dict[tuple[str, int], list] = {}
    for r in results:
        if r.expect == "escalate":
            groups.setdefault((r.env, r.task_seed), []).append(r)
    out = []
    for (env, seed), rs in sorted(groups.items()):
        if category_only:
            c = sum(1 for r in rs if r.escalated and r.reason != _CATEGORY_WRONG)
        else:
            c = sum(1 for r in rs if r.passed)
        out.append(TaskOutcome(env, seed, rs[0].tier, rs[0].expect, rs[0].kind, len(rs), c, c))
    return out


def curves(outcomes: list[TaskOutcome], k_max: int, seed: int, n_boot: int) -> dict:
    rng = random.Random(seed)
    m = len(outcomes)
    draws = [[outcomes[rng.randrange(m)] for _ in range(m)] for _ in range(n_boot)]

    def ci(fn, k):
        vals = sorted(mean([fn(o.n, o.c, k) for o in d]) for d in draws)
        return [round(vals[int(0.025 * n_boot)], 6), round(vals[int(0.975 * n_boot) - 1], 6)]

    res: dict = {"pass_at_k": {}, "pass_hat_k": {}, "pass_at_k_ci95": {}, "pass_hat_k_ci95": {}}
    for k in range(1, k_max + 1):
        res["pass_at_k"][str(k)] = round(mean([pass_at_k(o.n, o.c, k) for o in outcomes]), 6)
        res["pass_hat_k"][str(k)] = round(mean([pass_hat_k(o.n, o.c, k) for o in outcomes]), 6)
        res["pass_at_k_ci95"][str(k)] = ci(pass_at_k, k)
        res["pass_hat_k_ci95"][str(k)] = ci(pass_hat_k, k)
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

    results = []
    for env in ENVS:
        r, _ = evaluate_env(env, EscalateGuessAgent, n=a.n, k=a.k_max, seed=a.seed, n_boot=10)
        results.extend(r)
    cat = outcomes_for(results, True)
    full = outcomes_for(results, False)

    doc = {
        "label": "seeded random-category escalate-guesser (real harness run, no LLM) on escalate-expected tasks",
        "config": {"n": a.n, "k_max": a.k_max, "n_boot": a.n_boot, "envs": list(ENVS), "tasks": len(cat),
                   "tasks_by_env": {e: sum(1 for o in cat if o.env == e) for e in ENVS}},
        "escalate_guess": {
            "category_only": curves(cat, a.k_max, a.seed, a.n_boot),
            "full": curves(full, a.k_max, a.seed, a.n_boot),
        },
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/escalate_guess.py " + " ".join(argv if argv is not None else sys.argv[1:]),
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
