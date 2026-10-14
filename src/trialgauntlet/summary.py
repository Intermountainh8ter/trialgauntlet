"""Turn raw trial results into the per-environment summary stored in result files."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from trialgauntlet.metrics import (
    TaskOutcome,
    aggregate,
    bootstrap_ci,
    mean,
    pass_hat_curve,
    tally,
)
from trialgauntlet.models import TrialResult


def _metric_block(value: float, ci: tuple[float, float] | None) -> dict[str, Any]:
    block: dict[str, Any] = {"value": round(value, 6)}
    if ci is not None:
        block["ci"] = [round(ci[0], 6), round(ci[1], 6)]
    return block


def _subset(outcomes: Sequence[TaskOutcome], k: int) -> dict[str, Any]:
    agg = aggregate(outcomes, k)
    return {
        "tasks": len(outcomes),
        "pass@1": round(agg["pass@1"], 6),
        "pass@k": round(agg["pass@k"], 6),
        "pass^k": round(agg["pass^k"], 6),
    }


def summarize_env(
    results: Sequence[TrialResult],
    k: int,
    *,
    n_boot: int = 1000,
    ci_level: float = 0.95,
    seed: int = 0,
    price_in_per_m: float = 0.0,
    price_out_per_m: float = 0.0,
    include_timing: bool = True,
) -> dict[str, Any]:
    """Summarise all trials of one environment spec.

    Tasks with fewer than ``k`` trials cannot contribute to pass@k / pass^k and are listed under
    ``excluded_tasks`` instead of being silently dropped.
    """
    if not results:
        raise ValueError("no results to summarise")
    outcomes_all = tally(results)
    outcomes = [o for o in outcomes_all if o.n >= k]
    excluded = [o.seed for o in outcomes_all if o.n < k]
    if not outcomes:
        raise ValueError(f"no task has at least k={k} trials")
    agg = aggregate(outcomes, k)
    cis = bootstrap_ci(outcomes, k, n_boot=n_boot, level=ci_level, seed=seed)
    n_values = sorted({o.n for o in outcomes})
    by_tier: dict[str, list[TaskOutcome]] = defaultdict(list)
    by_expect: dict[str, list[TaskOutcome]] = defaultdict(list)
    for o in outcomes:
        by_tier[o.tier].append(o)
        by_expect[o.expect].append(o)
    kept = [r for r in results if r.task_seed not in set(excluded)]
    total_prompt = sum(r.prompt_tokens for r in kept)
    total_completion = sum(r.completion_tokens for r in kept)
    cost = total_prompt / 1e6 * price_in_per_m + total_completion / 1e6 * price_out_per_m
    outcome_only = mean([o.c_outcome / o.n for o in outcomes])
    summary: dict[str, Any] = {
        "tasks": len(outcomes),
        "trials": len(kept),
        "n": n_values[0] if len(n_values) == 1 else n_values,
        "k": k,
        "metrics": {
            "pass@1": _metric_block(agg["pass@1"], cis["pass@1"]),
            "pass@k": _metric_block(agg["pass@k"], cis["pass@k"]),
            "pass^k": _metric_block(agg["pass^k"], cis["pass^k"]),
            "gap": _metric_block(agg["gap"], cis["gap"]),
            "outcome_only": _metric_block(outcome_only, None),
        },
        "pass_hat_curve": [round(v, 6) for v in pass_hat_curve(outcomes, min(o.n for o in outcomes))],
        "by_tier": {t: _subset(os, k) for t, os in sorted(by_tier.items())},
        "by_expect": {e: _subset(os, k) for e, os in sorted(by_expect.items())},
        "usage": {
            "mean_steps": round(mean([r.steps for r in kept]), 4),
            "mean_prompt_tokens": round(mean([r.prompt_tokens for r in kept]), 2),
            "mean_completion_tokens": round(mean([r.completion_tokens for r in kept]), 2),
            "mean_agent_latency_s": round(mean([r.agent_latency_s for r in kept]), 6) if include_timing else None,
            "mean_wall_s": round(mean([r.wall_s for r in kept]), 6) if include_timing else None,
            "total_tokens": total_prompt + total_completion,
            "cost_usd": round(cost, 6),
        },
        "reliability": {
            "mean_tool_misuse": round(mean([r.misuse for r in kept]), 4),
            "mean_policy_violations": round(mean([len(r.violations) for r in kept]), 4),
            "violation_rate": round(mean([1.0 if r.violations else 0.0 for r in kept]), 4),
            "mean_format_errors": round(mean([r.format_errors for r in kept]), 4),
        },
        "terminated": dict(sorted(Counter(r.terminated for r in kept).items())),
        "per_task": [
            {
                "seed": o.seed, "tier": o.tier, "expect": o.expect, "kind": o.kind,
                "n": o.n, "c": o.c, "c_outcome": o.c_outcome,
            }
            for o in outcomes
        ],
        "excluded_tasks": excluded,
    }  # fmt: skip
    extras = _summarize_extra(kept)
    if extras:
        summary["extra"] = extras
    return summary


def _summarize_extra(results: Sequence[TrialResult]) -> dict[str, Any]:
    """Aggregate wrapper measurements (attack success, fault recovery) when present."""
    out: dict[str, Any] = {}
    attacked = [r for r in results if "attack_success" in r.extra]
    if attacked:
        asr = mean([1.0 if r.extra["attack_success"] else 0.0 for r in attacked])
        ok = [r for r in attacked if not r.extra["attack_success"]]
        out["injection"] = {
            "trials": len(attacked),
            "attack_success_rate": round(asr, 6),
            "utility_under_attack": round(mean([1.0 if r.passed else 0.0 for r in attacked]), 6),
            "utility_when_resisted": round(mean([1.0 if r.passed else 0.0 for r in ok]), 6) if ok else None,
        }
    faulted = [r for r in results if "faults_injected" in r.extra]
    if faulted:
        hit = [r for r in faulted if r.extra["faults_injected"] > 0]
        clean = [r for r in faulted if r.extra["faults_injected"] == 0]
        out["faults"] = {
            "trials": len(faulted),
            "mean_faults_injected": round(mean([float(r.extra["faults_injected"]) for r in faulted]), 4),
            "trials_with_fault": len(hit),
            "pass_rate_given_fault": round(mean([1.0 if r.passed else 0.0 for r in hit]), 6) if hit else None,
            "pass_rate_no_fault": round(mean([1.0 if r.passed else 0.0 for r in clean]), 6) if clean else None,
            "mean_retries_after_fault": round(mean([float(r.extra.get("retries_after_fault", 0)) for r in hit]), 4)
            if hit
            else None,
        }
    return out
