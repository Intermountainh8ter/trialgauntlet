"""Reliability metrics: pass@1, pass@k, pass^k (unbiased), aggregation and bootstrap CIs.

Definitions and the derivation of the estimators are in ``docs/METHODOLOGY.md``. Only the standard
library is used (``math.comb`` and ``random``).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import comb

from trialgauntlet.models import TrialResult


def _check(n: int, c: int, k: int | None = None) -> None:
    if n < 1:
        raise ValueError("need at least one trial (n >= 1)")
    if not 0 <= c <= n:
        raise ValueError(f"successes c={c} must satisfy 0 <= c <= n={n}")
    if k is not None:
        if k < 1:
            raise ValueError("k must be at least 1")
        if k > n:
            raise ValueError(f"k={k} exceeds the number of trials n={n}; run at least k trials per task")


def pass_at_1(n: int, c: int) -> float:
    """Probability one trial succeeds, estimated as c / n."""
    _check(n, c)
    return c / n


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that at least one of k trials succeeds: 1 - C(n-c, k) / C(n, k)."""
    _check(n, c, k)
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k: probability that all k trials succeed, C(c, k) / C(n, k). Unbiased for p^k."""
    _check(n, c, k)
    if c < k:
        return 0.0
    return comb(c, k) / comb(n, k)


@dataclass(frozen=True)
class TaskOutcome:
    """Trial tallies for one (environment, task seed)."""

    env: str
    seed: int
    tier: str
    expect: str
    kind: str
    n: int
    c: int
    c_outcome: int  # successes ignoring policy violations

    def metrics(self, k: int) -> tuple[float, float, float]:
        return pass_at_1(self.n, self.c), pass_at_k(self.n, self.c, k), pass_hat_k(self.n, self.c, k)


def tally(results: Iterable[TrialResult]) -> list[TaskOutcome]:
    """Group trial results into per-task outcomes (ordered by env then seed)."""
    groups: dict[tuple[str, int], list[TrialResult]] = defaultdict(list)
    for r in results:
        groups[(r.env, r.task_seed)].append(r)
    out = []
    for (env, seed), rs in sorted(groups.items()):
        first = rs[0]
        out.append(
            TaskOutcome(
                env=env,
                seed=seed,
                tier=first.tier,
                expect=first.expect,
                kind=first.kind,
                n=len(rs),
                c=sum(1 for r in rs if r.passed),
                c_outcome=sum(1 for r in rs if r.outcome_ok),
            )
        )
    return out


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty sequence")
    return sum(values) / len(values)


def aggregate(outcomes: Sequence[TaskOutcome], k: int) -> dict[str, float]:
    """Mean of the per-task metrics (every task weighs the same)."""
    if not outcomes:
        raise ValueError("no tasks to aggregate")
    rows = [o.metrics(k) for o in outcomes]
    p1 = mean([r[0] for r in rows])
    pk = mean([r[1] for r in rows])
    ph = mean([r[2] for r in rows])
    return {"pass@1": p1, "pass@k": pk, "pass^k": ph, "gap": p1 - ph}


def pass_hat_curve(outcomes: Sequence[TaskOutcome], k_max: int) -> list[float]:
    """pass^1 .. pass^k_max, suite level."""
    return [mean([pass_hat_k(o.n, o.c, k) for o in outcomes]) for k in range(1, k_max + 1)]


def percentile_interval(sorted_values: Sequence[float], level: float) -> tuple[float, float]:
    """Central percentile interval of an already sorted sample (floor/ceil rank rule)."""
    if not sorted_values:
        raise ValueError("empty sequence")
    size = len(sorted_values)
    alpha = (1.0 - level) / 2.0
    lo = max(0, math.floor(round(alpha * size, 9)))
    hi = min(size - 1, math.ceil(round((1.0 - alpha) * size, 9)) - 1)
    return sorted_values[lo], sorted_values[max(lo, hi)]


def bootstrap_ci(
    outcomes: Sequence[TaskOutcome],
    k: int,
    *,
    n_boot: int = 1000,
    level: float = 0.95,
    seed: int = 0,
) -> dict[str, tuple[float, float]]:
    """Percentile cluster bootstrap over tasks. Deterministic given ``seed``.

    Tasks are resampled with replacement and each drawn task keeps its observed per-task estimates.
    Those estimates already carry their own trial-to-trial noise, so the spread across tasks measures
    both sources of variance. Resampling the trials inside each drawn task as well would count the
    trial noise twice and, for the non-linear pass^k estimator, would be biased: the interval would
    sit above the (unbiased) point estimate.
    """
    if not outcomes:
        raise ValueError("no tasks to bootstrap")
    if not 0.0 < level < 1.0:
        raise ValueError("level must be in (0, 1)")
    rng = random.Random(seed)
    rows = [o.metrics(k) for o in outcomes]
    m = len(rows)
    samples: dict[str, list[float]] = {"pass@1": [], "pass@k": [], "pass^k": [], "gap": []}
    for _ in range(n_boot):
        s1 = sk = sh = 0.0
        for _ in range(m):
            p1, pk, ph = rows[rng.randrange(m)]
            s1 += p1
            sk += pk
            sh += ph
        samples["pass@1"].append(s1 / m)
        samples["pass@k"].append(sk / m)
        samples["pass^k"].append(sh / m)
        samples["gap"].append((s1 - sh) / m)
    out: dict[str, tuple[float, float]] = {}
    for name, vals in samples.items():
        vals.sort()
        out[name] = percentile_interval(vals, level)
    return out
