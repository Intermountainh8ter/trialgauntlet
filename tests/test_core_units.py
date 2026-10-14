from __future__ import annotations

import pytest

from trialgauntlet.budget import Budget, BudgetTracker
from trialgauntlet.models import Action, Grade, TaskSpec, ToolCall, ToolSpec, TrialResult, Usage
from trialgauntlet.schema import object_schema, validate_args
from trialgauntlet.seeds import derive_seed, rng_for


def test_derive_seed_golden_values_are_stable():
    assert derive_seed(0, "fleet", 3, 1) == 422401898
    assert derive_seed("a", "b") == 1884085485
    assert derive_seed("ab") == 2072912124
    assert derive_seed(1, 2, 3) == 2105978927


def test_derive_seed_separates_parts_and_fits_31_bits():
    assert derive_seed("a", "b") != derive_seed("ab")
    assert derive_seed(1, 2) != derive_seed(2, 1)
    assert 0 <= derive_seed("x") < 2**31


def test_rng_for_is_reproducible():
    assert [rng_for("k", 1).random() for _ in range(1)] == [rng_for("k", 1).random()]
    assert rng_for("k", 1).random() != rng_for("k", 2).random()


SCHEMA = object_schema(
    {
        "name": {"type": "string", "minLength": 2},
        "count": {"type": "integer", "minimum": 1, "maximum": 5},
        "mode": {"type": "string", "enum": ["a", "b"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "ratio": {"type": "number"},
        "flag": {"type": "boolean"},
    },
    required=["name"],
)


def test_valid_arguments_pass():
    ok = {"name": "ab", "count": 3, "mode": "a", "tags": ["x"], "ratio": 1, "flag": True}
    assert validate_args(SCHEMA, ok) == []


@pytest.mark.parametrize(
    "args,fragment",
    [
        ({}, "missing required argument 'name'"),
        ({"name": 3}, "expected string"),
        ({"name": "a"}, "at least 2"),
        ({"name": "ab", "count": "3"}, "expected integer"),
        ({"name": "ab", "count": True}, "expected integer"),
        ({"name": "ab", "count": 0}, "below the minimum"),
        ({"name": "ab", "count": 9}, "above the maximum"),
        ({"name": "ab", "mode": "z"}, "not one of"),
        ({"name": "ab", "tags": [1]}, "tags[0]"),
        ({"name": "ab", "extra": 1}, "unexpected argument 'extra'"),
        ({"name": "ab", "flag": "yes"}, "expected boolean"),
        ({"name": "ab", "ratio": "x"}, "expected number"),
    ],
)
def test_invalid_arguments_are_reported(args, fragment):
    problems = validate_args(SCHEMA, args)
    assert any(fragment in p for p in problems), problems


def test_non_object_arguments_rejected():
    assert validate_args(SCHEMA, ["x"])


def test_object_schema_defaults_to_all_required():
    s = object_schema({"a": {"type": "string"}, "b": {"type": "string"}})
    assert s["required"] == ["a", "b"] and s["additionalProperties"] is False


def test_budget_steps_boundary():
    t = BudgetTracker(Budget(max_steps=2))
    assert t.exceeded() is None
    t.charge_turn()
    assert t.exceeded() is None
    t.charge_turn()
    assert t.exceeded() == "steps"
    assert t.exceeded(include_steps=False) is None


def test_budget_tokens_and_time_with_fake_clock():
    now = [0.0]
    t = BudgetTracker(Budget(max_steps=99, max_tokens=100, max_seconds=5), clock=lambda: now[0])
    t.charge_turn(100)
    assert t.exceeded() is None  # equal to the limit is allowed
    t.charge_turn(1)
    assert t.exceeded() == "tokens"
    t2 = BudgetTracker(Budget(max_steps=99, max_seconds=5), clock=lambda: now[0])
    now[0] = 5.0
    assert t2.exceeded() is None
    now[0] = 5.1
    assert t2.exceeded() == "time"


def test_budget_roundtrip_ignores_unknown_keys():
    b = Budget(max_steps=7, max_tokens=9)
    assert Budget.from_dict({**b.to_dict(), "future": 1}) == b


def test_models_roundtrip():
    tc = ToolCall("x", {"a": 1}, id="c1")
    assert ToolCall.from_dict(tc.to_dict()) == tc
    act = Action(tool_call=tc, message="m", usage=Usage(3, 4), latency_s=0.5, format_error=None)
    assert Action.from_dict(act.to_dict()).tool_call == tc
    assert Action.from_dict(act.to_dict()).usage.total == 7
    assert Action.from_dict(Action().to_dict()).tool_call is None
    spec = TaskSpec("e", 1, "T1", "solve", "k", "s")
    assert TaskSpec.from_dict(spec.to_dict()) == spec
    g = Grade(True, True, [], "ok", True, False, {"a": 1})
    assert Grade.from_dict(g.to_dict()) == g


def test_toolspec_openai_shape():
    spec = ToolSpec("t", "desc", object_schema({"a": {"type": "string"}}))
    assert spec.to_openai() == {
        "type": "function",
        "function": {"name": "t", "description": "desc", "parameters": spec.parameters},
    }


def test_trial_result_roundtrip_and_total_tokens():
    r = TrialResult(
        env="e", task_seed=1, tier="T1", expect="solve", kind="k", trial=0, trial_seed=1, agent="a", passed=True,
        outcome_ok=True, finished=True, escalated=False, violations=["v"], reason="r", terminated="finish", steps=2,
        misuse=0, format_errors=0, prompt_tokens=3, completion_tokens=4, agent_latency_s=0.1, wall_s=0.2,
        state_digest="d", extra={"x": 1},
    )  # fmt: skip
    assert TrialResult.from_dict(r.to_dict()) == r
    assert r.total_tokens == 7
