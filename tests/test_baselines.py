from __future__ import annotations

import json

import pytest
from helpers import ToyEnv

from trialgauntlet.agents.baselines import AlwaysRefuseAgent, NoOpAgent, RandomToolAgent, _harvest
from trialgauntlet.agents.registry import BASELINES, DISPLAY, TRIVIAL, make_baseline
from trialgauntlet.envs import make_env
from trialgauntlet.models import EpisodeContext
from trialgauntlet.runner import run_trial
from trialgauntlet.schema import validate_args


def ctx_for(env, seed=0, trial_seed=1):
    return EpisodeContext(env.name, seed, 0, trial_seed, tuple(env.tools()), env.system_prompt(), 30)


def test_display_names_and_groups():
    assert list(DISPLAY.values()) == ["no-op", "random-tool", "always-refuse", "scripted-oracle", "greedy-unsafe"]
    assert TRIVIAL == ("noop", "random", "refuse") and set(TRIVIAL) < set(BASELINES)


def test_noop_never_calls_a_tool():
    agent = NoOpAgent()
    agent.start(ctx_for(ToyEnv()))
    for _ in range(3):
        assert agent.act("{}").tool_call is None


def test_always_refuse_escalates_once_with_fixed_arguments():
    env = ToyEnv()
    agent = AlwaysRefuseAgent()
    agent.start(ctx_for(env))
    first = agent.act("{}")
    assert first.tool_call.name == "escalate"
    assert first.tool_call.arguments == {"category": "impossible", "entity_id": "n/a", "reason": "refused"}
    assert agent.act("{}").tool_call is None
    agent.start(ctx_for(env))
    assert agent.act("{}").tool_call is not None


@pytest.mark.parametrize("name", ["fleet", "ledger", "config"])
def test_always_refuse_arguments_satisfy_the_schema(name):
    env = make_env(name)
    agent = AlwaysRefuseAgent()
    agent.start(ctx_for(env))
    call = agent.act("{}").tool_call
    spec = next(t for t in env.tools() if t.name == "escalate")
    assert validate_args(spec.parameters, call.arguments) == []


def test_harvest_collects_short_strings_only_once():
    out: list[str] = []
    _harvest({"a": "web-01", "b": ["web-01", {"c": "x" * 41}], "d": 5, "e": "two\nlines", "f": ""}, out)
    assert out == ["web-01"]


def test_random_agent_is_deterministic_per_trial_seed():
    env = make_env("fleet")

    def trace(trial_seed):
        agent = RandomToolAgent()
        agent.start(ctx_for(env, trial_seed=trial_seed))
        obs = env.reset(0)
        out = []
        for _ in range(12):
            tc = agent.act(obs).tool_call
            out.append((tc.name, json.dumps(tc.arguments, sort_keys=True)))
        return out

    assert trace(5) == trace(5)
    assert trace(5) != trace(6)


@pytest.mark.parametrize("name", ["fleet", "ledger", "config"])
def test_random_agent_mostly_emits_schema_valid_calls_and_learns_identifiers(name):
    env = make_env(name)
    agent = RandomToolAgent()
    agent.start(ctx_for(env, trial_seed=3))
    obs = env.reset(2)
    valid = total = 0
    specs = {t.name: t for t in env.tools()}
    for _ in range(200):
        tc = agent.act(obs).tool_call
        total += 1
        valid += not validate_args(specs[tc.name].parameters, tc.arguments)
        obs = '{"id": "web-r1-01", "status": "up"}' if total == 1 else obs
    assert valid / total > 0.4
    assert "web-r1-01" in agent._vocab


def test_random_agent_value_generation_covers_types():
    agent = RandomToolAgent()
    agent.start(ctx_for(ToyEnv()))
    assert agent._value({"type": "boolean"}) in (True, False)
    assert isinstance(agent._value({"type": "number"}), float)
    assert isinstance(agent._value({"type": "array", "items": {"type": "integer"}}), list)
    assert agent._value({"type": "string", "enum": ["only"]}) == "only"
    assert 3 <= agent._value({"type": "integer", "minimum": 3, "maximum": 5}) <= 5
    assert agent._value({"type": "integer", "minimum": 0, "maximum": 1000}) in (0, 1, 5, 100, 1000)
    assert 1 <= agent._value({"type": "integer", "minimum": 1}) <= 10
    assert agent._value({"type": "string"}) in ("x", "test", "1")


def test_make_baseline_factories():
    assert make_baseline("noop", "fleet")().name == "no-op"
    assert make_baseline("random", "fleet")().name == "random-tool"
    assert make_baseline("refuse", "fleet")().name == "always-refuse"
    assert make_baseline("oracle", "ledger")().name == "scripted-oracle"
    assert make_baseline("greedy", "config+naive")().name == "greedy-unsafe"
    with pytest.raises(KeyError, match="unknown baseline"):
        make_baseline("telepathy", "fleet")
    with pytest.raises(KeyError, match="no oracle agent"):
        make_baseline("oracle", "nowhere")


@pytest.mark.parametrize("name", ["fleet", "ledger", "config"])
def test_trivial_baselines_fail_on_a_spread_of_tasks(name):
    env = make_env(name)
    for key in TRIVIAL:
        for seed in env.task_seeds()[::5]:
            assert not run_trial(env, make_baseline(key, name)(), seed).passed
