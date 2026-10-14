"""Hand-verification of the estimators against enumerated small cases."""

from __future__ import annotations

from fractions import Fraction
from itertools import combinations
from math import comb

import pytest

from trialgauntlet.metrics import (
    TaskOutcome,
    aggregate,
    bootstrap_ci,
    pass_at_1,
    pass_at_k,
    pass_hat_curve,
    pass_hat_k,
    percentile_interval,
    tally,
)
from trialgauntlet.models import TrialResult


def enumerate_exact(outcomes: list[bool], k: int) -> tuple[Fraction, Fraction]:
    """Fraction of k-subsets of the trials that are all-success / contain a success."""
    subsets = list(combinations(range(len(outcomes)), k))
    all_ok = sum(1 for s in subsets if all(outcomes[i] for i in s))
    any_ok = sum(1 for s in subsets if any(outcomes[i] for i in s))
    return Fraction(all_ok, len(subsets)), Fraction(any_ok, len(subsets))


@pytest.mark.parametrize("n,k", [(n, k) for n in range(1, 8) for k in range(1, n + 1)])
def test_closed_forms_equal_subset_enumeration(n, k):
    for c in range(n + 1):
        outcomes = [True] * c + [False] * (n - c)
        exact_all, exact_any = enumerate_exact(outcomes, k)
        assert pass_hat_k(n, c, k) == pytest.approx(float(exact_all), abs=1e-12)
        assert pass_at_k(n, c, k) == pytest.approx(float(exact_any), abs=1e-12)
        assert pass_at_1(n, c) == pytest.approx(c / n)


def test_enumeration_is_order_independent():
    a = enumerate_exact([True, False, True, True, False], 3)
    b = enumerate_exact([False, False, True, True, True], 3)
    assert a == b == (Fraction(1, 10), Fraction(10, 10))


@pytest.mark.parametrize(
    "n,c,k,p1,pk,ph",
    [
        (4, 2, 2, 0.5, 5 / 6, 1 / 6),
        (8, 6, 4, 0.75, 1.0, 15 / 70),
        (8, 4, 4, 0.5, 1 - 1 / 70, 1 / 70),
        (8, 2, 4, 0.25, 1 - comb(6, 4) / 70, 0.0),
        (8, 8, 4, 1.0, 1.0, 1.0),
        (8, 0, 4, 0.0, 0.0, 0.0),
        (5, 3, 3, 0.6, 1.0, 0.1),
        (10, 7, 3, 0.7, 1 - 1 / 120, 35 / 120),
    ],
)
def test_documented_examples(n, c, k, p1, pk, ph):
    assert pass_at_1(n, c) == pytest.approx(p1)
    assert pass_at_k(n, c, k) == pytest.approx(pk)
    assert pass_hat_k(n, c, k) == pytest.approx(ph)


def test_documented_example_rounding_matches_methodology_table():
    assert round(pass_hat_k(8, 6, 4), 4) == 0.2143
    assert round(pass_at_k(8, 4, 4), 4) == 0.9857
    assert round(pass_hat_k(10, 7, 3), 4) == 0.2917
    assert round((6 / 8) ** 4, 4) == 0.3164  # the biased plug-in the docs warn about


@pytest.mark.parametrize("n,c,k", [(n, c, k) for n in range(1, 9) for c in range(n + 1) for k in range(1, n + 1)])
def test_ordering_pass_hat_le_pass1_le_pass_at_k(n, c, k):
    assert pass_hat_k(n, c, k) <= pass_at_1(n, c) + 1e-12
    assert pass_at_1(n, c) <= pass_at_k(n, c, k) + 1e-12


def test_k_equals_one_collapses_to_pass_at_1():
    for n in range(1, 7):
        for c in range(n + 1):
            assert pass_hat_k(n, c, 1) == pytest.approx(pass_at_1(n, c))
            assert pass_at_k(n, c, 1) == pytest.approx(pass_at_1(n, c))


def test_k_equals_n_pass_hat_is_all_or_nothing():
    assert pass_hat_k(5, 5, 5) == 1.0
    assert pass_hat_k(5, 4, 5) == 0.0
    assert pass_at_k(5, 0, 5) == 0.0
    assert pass_at_k(5, 1, 5) == 1.0


@pytest.mark.parametrize(
    "n,k,p", [(2, 2, Fraction(1, 2)), (5, 3, Fraction(2, 3)), (6, 2, Fraction(1, 5)), (4, 4, Fraction(9, 10))]
)
def test_pass_hat_k_is_exactly_unbiased_for_p_to_the_k(n, k, p):
    expected = sum(comb(n, c) * p**c * (1 - p) ** (n - c) * Fraction(comb(c, k), comb(n, k)) for c in range(n + 1))
    assert expected == p**k


@pytest.mark.parametrize("n,k,p", [(2, 2, Fraction(1, 2)), (5, 3, Fraction(2, 3)), (6, 2, Fraction(1, 5))])
def test_pass_at_k_is_exactly_unbiased_for_one_minus_q_to_the_k(n, k, p):
    expected = sum(
        comb(n, c) * p**c * (1 - p) ** (n - c) * (1 - Fraction(comb(n - c, k), comb(n, k))) for c in range(n + 1)
    )
    assert expected == 1 - (1 - p) ** k


def test_naive_plug_in_is_biased_upward():
    n, k, p = 2, 2, Fraction(1, 2)
    naive = sum(comb(n, c) * p**c * (1 - p) ** (n - c) * Fraction(c, n) ** k for c in range(n + 1))
    assert naive == Fraction(3, 8)
    assert naive > p**k


@pytest.mark.parametrize(
    "args",
    [(0, 0, 1), (3, 4, 1), (3, -1, 1), (3, 2, 0), (3, 2, 4)],
)
def test_invalid_inputs_raise(args):
    with pytest.raises(ValueError):
        pass_hat_k(*args)
    with pytest.raises(ValueError):
        pass_at_k(*args)


def test_pass_at_1_validates():
    with pytest.raises(ValueError):
        pass_at_1(0, 0)
    with pytest.raises(ValueError):
        pass_at_1(2, 3)


def outcome(c, n=8, seed=0, tier="T1", expect="solve"):
    return TaskOutcome("e", seed, tier, expect, "kind", n, c, c)


def test_aggregate_two_task_example_from_docs():
    agg = aggregate([outcome(8), outcome(4, seed=1)], 4)
    assert agg["pass@1"] == pytest.approx(0.75)
    assert agg["pass^k"] == pytest.approx((1 + 1 / 70) / 2)
    assert agg["pass@k"] == pytest.approx((1 + 69 / 70) / 2)
    assert agg["gap"] == pytest.approx(0.75 - (1 + 1 / 70) / 2)


def test_aggregate_rejects_empty_and_too_few_trials():
    with pytest.raises(ValueError):
        aggregate([], 2)
    with pytest.raises(ValueError):
        aggregate([outcome(1, n=2)], 3)


def test_pass_hat_curve_is_non_increasing():
    curve = pass_hat_curve([outcome(6), outcome(3, seed=1), outcome(8, seed=2)], 8)
    assert curve[0] == pytest.approx((6 / 8 + 3 / 8 + 1) / 3)
    assert all(a >= b - 1e-12 for a, b in zip(curve, curve[1:]))
    assert curve[-1] == pytest.approx(1 / 3)


def make_result(seed, trial, passed, outcome_ok=None, env="e"):
    return TrialResult(
        env=env, task_seed=seed, tier="T1", expect="solve", kind="k", trial=trial, trial_seed=0, agent="a",
        passed=passed, outcome_ok=passed if outcome_ok is None else outcome_ok, finished=True, escalated=False,
        violations=[], reason="", terminated="finish", steps=1, misuse=0, format_errors=0, prompt_tokens=0,
        completion_tokens=0, agent_latency_s=0.0, wall_s=0.0, state_digest="d",
    )  # fmt: skip


def test_tally_groups_and_counts():
    results = [make_result(1, t, t < 2) for t in range(4)] + [
        make_result(0, 0, True),
        make_result(0, 1, False, outcome_ok=True),
    ]
    outs = tally(results)
    assert [(o.seed, o.n, o.c, o.c_outcome) for o in outs] == [(0, 2, 1, 2), (1, 4, 2, 2)]


def test_bootstrap_is_deterministic_and_ordered():
    outs = [outcome(c, seed=i) for i, c in enumerate([8, 6, 4, 2, 0, 7, 5, 3])]
    a = bootstrap_ci(outs, 4, n_boot=200, seed=1)
    b = bootstrap_ci(outs, 4, n_boot=200, seed=1)
    c = bootstrap_ci(outs, 4, n_boot=200, seed=2)
    assert a == b
    assert a != c
    point = aggregate(outs, 4)
    for name in ("pass@1", "pass@k", "pass^k"):
        lo, hi = a[name]
        assert 0.0 <= lo <= hi <= 1.0
        assert lo - 0.15 <= point[name] <= hi + 0.15


def test_bootstrap_degenerate_for_deterministic_agent():
    outs = [outcome(8, seed=i) for i in range(5)]
    ci = bootstrap_ci(outs, 4, n_boot=50)
    assert ci["pass@1"] == (1.0, 1.0)
    outs = [outcome(0, seed=i) for i in range(5)]
    assert bootstrap_ci(outs, 4, n_boot=50)["pass^k"] == (0.0, 0.0)


def test_bootstrap_ci_widens_with_fewer_tasks():
    many = [outcome(c, seed=i) for i, c in enumerate([8, 4, 0, 6, 2] * 8)]
    few = many[:5]
    w_many = bootstrap_ci(many, 4, n_boot=300)["pass@1"]
    w_few = bootstrap_ci(few, 4, n_boot=300)["pass@1"]
    assert (w_few[1] - w_few[0]) > (w_many[1] - w_many[0])


def test_bootstrap_validates():
    with pytest.raises(ValueError):
        bootstrap_ci([], 2)
    with pytest.raises(ValueError):
        bootstrap_ci([outcome(1)], 2, level=1.5)


def test_percentile_interval_rank_rule():
    vals = [float(i) for i in range(1000)]
    assert percentile_interval(vals, 0.95) == (25.0, 974.0)
    assert percentile_interval([1.0], 0.95) == (1.0, 1.0)
    with pytest.raises(ValueError):
        percentile_interval([], 0.95)
