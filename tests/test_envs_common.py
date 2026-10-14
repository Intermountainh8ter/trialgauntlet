"""Properties every built-in environment must satisfy, checked on every task seed."""

from __future__ import annotations

import json

import pytest

from trialgauntlet.envs import GREEDY, ORACLES, env_names, make_env
from trialgauntlet.models import ToolCall
from trialgauntlet.runner import replay_trajectory, run_trial
from trialgauntlet.trajectory import MemoryRecorder, TrajectoryWriter

NAMES = ["fleet", "ledger", "config"]
ALL = [(n, s) for n in NAMES for s in make_env(n).task_seeds()]
SOLVE = [(n, s) for n, s in ALL if make_env(n).task(s).expect == "solve"]
ESCALATE = [(n, s) for n, s in ALL if make_env(n).task(s).expect == "escalate"]


def test_registry_has_the_three_environments():
    assert set(NAMES) <= set(env_names())
    with pytest.raises(KeyError, match="unknown environment"):
        make_env("nope")


@pytest.mark.parametrize("name", NAMES)
def test_at_least_forty_tasks_with_three_tiers_and_an_unsolvable_subset(name):
    env = make_env(name)
    specs = env.task_specs()
    assert len(specs) >= 40
    assert [s.seed for s in specs] == list(range(len(specs)))
    assert {s.tier for s in specs} == {"T1", "T2", "T3"}
    assert {s.expect for s in specs} == {"solve", "escalate"}
    kinds = {s.kind for s in specs}
    assert sum(k.startswith("esc_") for k in kinds) >= 3
    for tier in ("T1", "T2", "T3"):
        assert sum(1 for s in specs if s.tier == tier and s.expect == "solve") >= 8
    assert all(s.kind.startswith("esc_") == (s.expect == "escalate") for s in specs)


@pytest.mark.parametrize("name", NAMES)
def test_task_lookup_and_unknown_seed(name):
    env = make_env(name)
    assert env.task(0).seed == 0
    with pytest.raises(KeyError):
        env.task(10_000)


@pytest.mark.parametrize("name,seed", ALL)
def test_scripted_oracle_gets_every_task_right(name, seed):
    env = make_env(name)
    r = run_trial(env, ORACLES[name](), seed)
    assert r.passed, (r.kind, r.reason, r.violations)
    assert r.violations == [] and r.misuse == 0
    assert r.terminated == ("escalate" if env.task(seed).expect == "escalate" else "finish")


@pytest.mark.parametrize("name,seed", ALL)
def test_greedy_unsafe_never_passes(name, seed):
    r = run_trial(make_env(name), GREEDY[name](), seed)
    assert not r.passed


@pytest.mark.parametrize("name", NAMES)
def test_greedy_often_gets_the_outcome_but_policy_grading_catches_it(name):
    env = make_env(name)
    rs = [run_trial(env, GREEDY[name](), s) for s in env.task_seeds()]
    outcome = sum(r.outcome_ok for r in rs)
    assert outcome >= 5, "greedy should achieve some outcomes, otherwise the policy check proves nothing"
    assert all(r.violations for r in rs if r.outcome_ok), "every outcome-correct greedy run must violate policy"


@pytest.mark.parametrize("name,seed", ALL)
def test_reset_is_deterministic(name, seed):
    a, b = make_env(name), make_env(name)
    assert a.reset(seed) == b.reset(seed) == a.reset(seed)
    assert a.state_digest() == b.state_digest()
    json.loads(a.reset(seed))  # first observation is a JSON document


@pytest.mark.parametrize("name", NAMES)
def test_different_seeds_give_different_worlds(name):
    env = make_env(name)
    digests = set()
    for seed in env.task_seeds():
        env.reset(seed)
        digests.add(env.state_digest())
    assert len(digests) == len(env.task_seeds())


@pytest.mark.parametrize("name,seed", SOLVE)
def test_solvable_tasks_are_not_solved_at_reset(name, seed):
    """The degenerate-success guard at the grader level: doing nothing can never satisfy a solve task."""
    env = make_env(name)
    env.reset(seed)
    solved, _, _ = env._check_solved()
    assert not solved
    assert not env.grade().passed


@pytest.mark.parametrize("name,seed", SOLVE)
def test_finish_without_acting_fails_on_solvable_tasks(name, seed):
    env = make_env(name)
    env.reset(seed)
    env.step(ToolCall("finish", {"summary": "nothing needed"}))
    assert not env.grade().passed


@pytest.mark.parametrize("name,seed", ESCALATE)
def test_finish_instead_of_escalating_fails_and_expected_escalation_is_defined(name, seed):
    env = make_env(name)
    env.reset(seed)
    assert env._expected_escalation() is not None
    env.step(ToolCall("finish", {"summary": "done"}))
    assert not env.grade().passed


@pytest.mark.parametrize("name,seed", ESCALATE)
def test_fixed_escalation_without_the_entity_fails(name, seed):
    env = make_env(name)
    env.reset(seed)
    for cat in env.escalation_categories:
        env.reset(seed)
        env.step(ToolCall("escalate", {"category": cat, "entity_id": "unknown", "reason": "no"}))
        assert not env.grade().passed


@pytest.mark.parametrize("name", NAMES)
def test_tool_schemas_are_well_formed(name):
    tools = make_env(name).tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    assert {"finish", "escalate"} <= set(names)
    for t in tools:
        assert t.description.strip()
        assert t.parameters["type"] == "object" and t.parameters["additionalProperties"] is False
        assert set(t.parameters["required"]) <= set(t.parameters["properties"])
        assert t.terminal == (t.name in ("finish", "escalate"))
    esc = next(t for t in tools if t.name == "escalate")
    assert tuple(esc.parameters["properties"]["category"]["enum"]) == make_env(name).escalation_categories


@pytest.mark.parametrize("name", NAMES)
def test_system_prompt_states_escalation_categories_and_rules(name):
    env = make_env(name)
    prompt = env.system_prompt()
    for cat in env.escalation_categories:
        assert cat in prompt
    assert "finish" in prompt and "escalate" in prompt


@pytest.mark.parametrize("name", NAMES)
def test_unknown_tool_and_bad_arguments_are_misuse_not_crashes(name):
    env = make_env(name)
    env.reset(0)
    assert env.step(ToolCall("definitely_not_a_tool", {})).misuse
    first = next(t for t in env.tools() if t.parameters["required"])
    res = env.step(ToolCall(first.name, {}))
    assert res.misuse and res.is_error
    res = env.step(ToolCall(first.name, {**dict.fromkeys(first.parameters["required"], 1), "bogus": 1}))
    assert res.misuse


@pytest.mark.parametrize("name", NAMES)
def test_oracle_trajectories_replay_to_identical_grade(name, tmp_path):
    env = make_env(name)
    for seed in env.task_seeds()[:: max(1, len(env.task_seeds()) // 9)]:
        path = tmp_path / f"{name}-{seed}.jsonl"
        run_trial(make_env(name), ORACLES[name](), seed, env_spec=name, recorder=TrajectoryWriter(path))
        report = replay_trajectory(path)
        assert report.ok, report.mismatches
        assert report.replayed.state_digest == report.original.state_digest


@pytest.mark.parametrize("name", NAMES)
def test_environment_is_reusable_across_resets(name):
    env = make_env(name)
    first = run_trial(env, ORACLES[name](), 3)
    second = run_trial(env, ORACLES[name](), 3)
    assert first.state_digest == second.state_digest and first.passed and second.passed


@pytest.mark.parametrize("name", NAMES)
def test_observations_are_json(name):
    env = make_env(name)
    rec = MemoryRecorder()
    run_trial(env, ORACLES[name](), 5, recorder=rec)
    for step in rec.records[1:-1]:
        json.loads(step["observation"])
