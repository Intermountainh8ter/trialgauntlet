"""Glue used by the CLI and the audit: select tasks, run an agent on an environment, summarise."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from trialgauntlet.budget import Budget
from trialgauntlet.envs import make_env
from trialgauntlet.models import TrialResult
from trialgauntlet.protocols import Agent
from trialgauntlet.runner import run_suite
from trialgauntlet.summary import summarize_env


def select_seeds(
    spec: str, *, tiers: Sequence[str] | None = None, kinds: Sequence[str] | None = None, limit: int | None = None
) -> list[int]:
    """Task seeds of environment ``spec`` filtered by tier, kind and a per-environment limit."""
    seeds = []
    for task in make_env(spec).task_specs():
        if tiers and task.tier not in tiers:
            continue
        if kinds and task.kind not in kinds:
            continue
        seeds.append(task.seed)
    if limit is not None:
        seeds = seeds[:limit]
    if not seeds:
        raise ValueError(f"no tasks of '{spec}' match the requested filters")
    return seeds


def evaluate_env(
    spec: str,
    make_agent: Callable[[], Agent],
    *,
    n: int,
    k: int,
    seed: int = 0,
    seeds: Sequence[int] | None = None,
    budget: Budget | None = None,
    run_dir: Path | None = None,
    resume: bool = True,
    n_boot: int = 1000,
    ci_level: float = 0.95,
    include_timing: bool = True,
    price_in_per_m: float = 0.0,
    price_out_per_m: float = 0.0,
    on_trial: Callable[[TrialResult, bool], None] | None = None,
) -> tuple[list[TrialResult], dict[str, Any]]:
    """Run ``n`` trials of every selected task of ``spec`` and summarise them."""
    if k > n:
        raise ValueError(f"k={k} must not exceed n={n}: pass^k needs at least k trials per task")
    task_seeds = list(seeds) if seeds is not None else make_env(spec).task_seeds()
    results = run_suite(
        lambda: make_env(spec),
        make_agent,
        task_seeds,
        n,
        env_spec=spec,
        run_seed=seed,
        budget=budget,
        run_dir=run_dir,
        resume=resume,
        on_trial=on_trial,
    )
    summary = summarize_env(
        results,
        k,
        n_boot=n_boot,
        ci_level=ci_level,
        seed=seed,
        price_in_per_m=price_in_per_m,
        price_out_per_m=price_out_per_m,
        include_timing=include_timing,
    )
    return results, summary
