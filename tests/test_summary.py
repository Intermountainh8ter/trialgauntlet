from __future__ import annotations

import pytest
from helpers import ListAgent, ToyEnv, ToyOracle, tc

from trialgauntlet.runner import run_suite
from trialgauntlet.summary import summarize_env


def test_summary_for_oracle_is_perfect_and_ci_degenerate():
    results = run_suite(ToyEnv, ToyOracle, range(10), 4, env_spec="toy")
    s = summarize_env(results, 4, n_boot=100)
    assert s["tasks"] == 10 and s["trials"] == 40 and s["n"] == 4 and s["k"] == 4
    for name in ("pass@1", "pass@k", "pass^k"):
        assert s["metrics"][name]["value"] == 1.0 and s["metrics"][name]["ci"] == [1.0, 1.0]
    assert s["metrics"]["gap"]["value"] == 0.0
    assert s["by_expect"]["escalate"]["tasks"] == 2 and s["by_expect"]["solve"]["tasks"] == 8
    assert set(s["by_tier"]) == {"T1", "T2"}
    assert s["terminated"] == {"escalate": 8, "finish": 32}
    assert len(s["pass_hat_curve"]) == 4 and s["pass_hat_curve"][-1] == 1.0
    assert s["reliability"]["violation_rate"] == 0.0 and s["usage"]["cost_usd"] == 0.0


def test_summary_for_failing_agent():
    results = run_suite(ToyEnv, lambda: ListAgent([]), range(5), 3, env_spec="toy")
    s = summarize_env(results, 2, n_boot=50)
    assert s["metrics"]["pass@1"]["value"] == 0.0 and s["terminated"] == {"no_action": 15}
    assert s["metrics"]["outcome_only"]["value"] == 0.0


def test_tasks_with_too_few_trials_are_reported_not_hidden():
    results = run_suite(ToyEnv, ToyOracle, [0, 1], 3, env_spec="toy")
    results += run_suite(ToyEnv, ToyOracle, [2], 1, env_spec="toy")
    s = summarize_env(results, 3, n_boot=20)
    assert s["tasks"] == 2 and s["excluded_tasks"] == [2]


def test_all_tasks_excluded_raises():
    results = run_suite(ToyEnv, ToyOracle, [0], 1, env_spec="toy")
    with pytest.raises(ValueError, match="at least k"):
        summarize_env(results, 3)
    with pytest.raises(ValueError):
        summarize_env([], 1)


def test_cost_uses_per_million_prices():
    results = run_suite(
        ToyEnv,
        lambda: ListAgent([tc("add", n=2), tc("finish", summary="")], tokens_per_turn=1_000_000),
        [0],
        2,
        env_spec="toy",
    )
    s = summarize_env(results, 2, n_boot=10, price_in_per_m=1.0, price_out_per_m=2.0)
    # 2 trials x 2 turns x (0.5M prompt + 0.5M completion)
    assert s["usage"]["total_tokens"] == 4_000_000
    assert s["usage"]["cost_usd"] == pytest.approx(2.0 * 1.0 + 2.0 * 2.0)


def test_summary_is_deterministic_for_fixed_seed():
    results = run_suite(
        ToyEnv, lambda: ListAgent([tc("add", n=2)] * 0 + [tc("finish", summary="")]), range(10), 4, env_spec="toy"
    )
    a = summarize_env(results, 2, n_boot=50, seed=3)
    b = summarize_env(results, 2, n_boot=50, seed=3)
    assert a == b


def test_extra_blocks_aggregate_attack_and_fault_fields():
    results = run_suite(ToyEnv, ToyOracle, range(4), 2, env_spec="toy")
    for i, r in enumerate(results):
        r.extra = {"attack_success": i % 2 == 0, "faults_injected": i % 3, "retries_after_fault": 1}
    s = summarize_env(results, 2, n_boot=10)
    assert s["extra"]["injection"]["attack_success_rate"] == 0.5
    assert s["extra"]["faults"]["trials_with_fault"] == 5
    assert s["extra"]["faults"]["pass_rate_no_fault"] == 1.0
