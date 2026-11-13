#!/usr/bin/env python3
"""First k where pass^k of a SIMULATED tier-dependent oracle with a per-trial symmetric outcome flip falls below
the flip-free curve by more than a SESOI. Mock flip rates only; no model is run. Standard library plus the
trialgauntlet package only."""

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

from trialgauntlet.envs import make_env  # noqa: E402
from trialgauntlet.metrics import TaskOutcome, mean, pass_hat_k  # noqa: E402

ENVS = ("fleet", "ledger", "config")
TIER_P = {"T1": 0.95, "T2": 0.85, "T3": 0.60}
# MOCK flip rates, not measured from any serving stack.
FLIP_RATES = (0.02, 0.05, 0.10)
SESOI = 0.05
K_MAX = 8
K_LIMIT = 4


def simulate(seed: int, n: int, flip: float) -> list[TaskOutcome]:
    """Seeded Bernoulli trials per task; each trial outcome is then flipped with probability ``flip``."""
    rng = random.Random(seed)
    flip_rng = random.Random(seed + 1_000_003)
    out = []
    for env in ENVS:
        for t in make_env(env).task_specs():
            c = 0
            for _ in range(n):
                ok = rng.random() < TIER_P[t.tier]
                if flip_rng.random() < flip:
                    ok = not ok
                c += ok
            out.append(TaskOutcome(env, t.seed, t.tier, t.expect, t.kind, n, c, c))
    return out


def curve(outcomes: list[TaskOutcome], k_max: int) -> list[float]:
    return [mean([pass_hat_k(o.n, o.c, k) for o in outcomes]) for k in range(1, k_max + 1)]


def first_divergent(base: list[float], cur: list[float], sesoi: float, k_limit: int) -> int | None:
    for k in range(1, k_limit + 1):
        if base[k - 1] - cur[k - 1] > sesoi:
            return k
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    base = curve(simulate(a.seed, a.n, 0.0), K_MAX)
    per_rate = {}
    firsts = []
    for f in FLIP_RATES:
        cur = curve(simulate(a.seed, a.n, f), K_MAX)
        fd = first_divergent(base, cur, SESOI, K_LIMIT)
        firsts.append(fd)
        per_rate[str(f)] = {
            "pass_hat": [round(x, 6) for x in cur],
            "gap_to_flip_free": [round(b - x, 6) for b, x in zip(base, cur)],
            "k_first_divergent": fd,
        }
    big = [x if x is not None else K_LIMIT + 1 for x in firsts]
    monotone = all(big[i] >= big[i + 1] for i in range(len(big) - 1))
    doc = {
        "label": "SIMULATED tier-dependent oracle with a MOCK symmetric per-trial flip; no model was run",
        "config": {"n": a.n, "k_max": K_MAX, "k_limit": K_LIMIT, "sesoi": SESOI, "tier_p": TIER_P,
                   "flip_rates": list(FLIP_RATES), "tasks": 138},
        "flip_free_pass_hat": [round(x, 6) for x in base],
        "flip_passk": {
            "k_first_divergent": firsts[-1],
            "k_first_divergent_by_rate": dict(zip((str(f) for f in FLIP_RATES), firsts)),
            "first_divergence_non_increasing_in_rate": monotone,
            "by_rate": per_rate,
        },
        "provenance": {
            "started_at": started,
            "seeds": [a.seed],
            "command": "python3 scripts/flip_passk_sesoi.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "hardware": f"{platform.machine()} {platform.system()} python {platform.python_version()}, cpu only",
            "wall_s": round(time.time() - t0, 3),
            "data_sources": [
                {"url": "https://github.com/ggml-org/llama.cpp/issues/22450",
                 "license": "MIT (reference only; no data used, all trials simulated)"}
            ],
        },
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
