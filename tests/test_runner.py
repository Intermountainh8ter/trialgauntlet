from __future__ import annotations

import json

import pytest
from helpers import ListAgent, ToyEnv, ToyOracle, tc

from trialgauntlet.budget import Budget
from trialgauntlet.models import Action, EpisodeContext
from trialgauntlet.protocols import Agent
from trialgauntlet.runner import NUDGE, ResumeError, run_suite, run_trial
from trialgauntlet.seeds import derive_seed
from trialgauntlet.trajectory import MemoryRecorder


def solve_calls(target=2):
    return [tc("add", n=target), tc("finish", summary="ok")]


def test_oracle_passes_every_toy_task():
    env = ToyEnv()
    for seed in env.task_seeds():
        r = run_trial(env, ToyOracle(), seed)
        assert r.passed and r.outcome_ok, (seed, r.reason)
        assert r.terminated == ("escalate" if env.task(seed).expect == "escalate" else "finish")


def test_noop_agent_is_nudged_once_then_ends():
    env = ToyEnv()
    agent = ListAgent([])
    r = run_trial(env, agent, 0)
    assert not r.passed
    assert r.terminated == "no_action"
    assert agent.observations.count(NUDGE) == 1
    assert r.steps == 0


def test_no_nudges_when_budget_says_zero():
    agent = ListAgent([])
    run_trial(ToyEnv(), agent, 0, budget=Budget(max_nudges=0))
    assert NUDGE not in agent.observations


def test_finish_without_work_fails_with_reason():
    r = run_trial(ToyEnv(), ListAgent([tc("finish", summary="x")]), 0)
    assert not r.passed and r.finished and not r.outcome_ok
    assert r.reason == "counter != target"


def test_escalating_a_solvable_task_fails():
    r = run_trial(ToyEnv(), ListAgent([tc("escalate", category="impossible", entity_id="counter", reason="r")]), 0)
    assert not r.passed and r.escalated and "solvable" in r.reason


def test_escalating_impossible_task_requires_category_and_entity():
    env = ToyEnv()
    good = run_trial(env, ListAgent([tc("escalate", category="impossible", entity_id="Counter ", reason="")]), 4)
    assert good.passed
    wrong_cat = run_trial(env, ListAgent([tc("escalate", category="other", entity_id="counter", reason="")]), 4)
    assert not wrong_cat.passed and "category" in wrong_cat.reason
    wrong_entity = run_trial(env, ListAgent([tc("escalate", category="impossible", entity_id="nope", reason="")]), 4)
    assert not wrong_entity.passed and "entity" in wrong_entity.reason


def test_changing_state_before_escalating_fails():
    calls = [tc("add", n=1), tc("escalate", category="impossible", entity_id="counter", reason="")]
    r = run_trial(ToyEnv(), ListAgent(calls), 4)
    assert not r.passed and "state was changed" in r.reason


def test_not_escalating_an_impossible_task_fails():
    r = run_trial(ToyEnv(), ListAgent([tc("finish", summary="")]), 4)
    assert not r.passed and "did not escalate" in r.reason


def test_policy_violation_fails_trial_but_outcome_is_ok():
    calls = [tc("add", n=-1), tc("add", n=3), tc("finish", summary="")]
    r = run_trial(ToyEnv(), ListAgent(calls), 0)
    assert r.outcome_ok and not r.passed
    assert r.violations == ["negative_add"]
    assert "negative_add" in r.reason


def test_misuse_is_counted_for_unknown_tool_bad_args_and_bad_values():
    calls = [tc("nope"), tc("add", n="x"), tc("add", n=10**9), tc("add", n=2), tc("finish", summary="")]
    r = run_trial(ToyEnv(), ListAgent(calls), 0)
    assert r.misuse == 3 and r.passed and r.steps == 5


def test_step_after_done_is_an_error():
    env = ToyEnv()
    env.reset(0)
    env.step(tc("finish", summary=""))
    res = env.step(tc("peek"))
    assert res.is_error and res.done


def test_step_before_reset_raises():
    with pytest.raises(RuntimeError):
        ToyEnv().step(tc("peek"))
    with pytest.raises(RuntimeError):
        ToyEnv().grade()


def test_format_errors_end_the_trial_after_three_in_a_row():
    agent = ListAgent([None, None, None], format_error="tool_call_as_text")
    r = run_trial(ToyEnv(), agent, 0)
    assert r.terminated == "format_error" and r.format_errors == 3 and not r.passed
    assert json.loads(agent.observations[1])["error"] == "format_error"


def test_format_error_streak_resets_after_a_valid_call():
    calls = [None, None, tc("peek"), None, None, tc("add", n=2), tc("finish", summary="")]
    r = run_trial(ToyEnv(), ListAgent(calls, format_error="malformed_arguments"), 0)
    assert r.passed and r.format_errors == 4


def test_step_budget_boundary_is_inclusive_of_last_allowed_turn():
    assert run_trial(ToyEnv(), ListAgent(solve_calls()), 0, budget=Budget(max_steps=2)).passed
    r = run_trial(ToyEnv(), ListAgent(solve_calls()), 0, budget=Budget(max_steps=1))
    assert r.terminated == "budget:steps" and not r.passed


def test_budget_exceeded_overrides_a_passing_grade():
    env = ToyEnv()
    r = run_trial(env, ListAgent(solve_calls()), 0, budget=Budget(max_steps=2))
    assert r.passed
    # Same behaviour but the token budget trips before `finish` executes.
    r2 = run_trial(ToyEnv(), ListAgent(solve_calls(), tokens_per_turn=100), 0, budget=Budget(max_tokens=150))
    assert r2.terminated == "budget:tokens" and not r2.passed and "budget:tokens" in r2.reason
    assert r2.steps == 1  # the over-budget second turn was dropped, not executed


def test_time_budget_with_fake_clock():
    ticks = iter(range(0, 1000))
    r = run_trial(ToyEnv(), ListAgent(solve_calls()), 0, budget=Budget(max_seconds=3), clock=lambda: float(next(ticks)))
    assert r.terminated == "budget:time" and not r.passed


def test_token_and_latency_accounting():
    class Metered(ListAgent):
        def act(self, observation):
            a = super().act(observation)
            a.latency_s = 0.25
            return a

    r = run_trial(ToyEnv(), Metered(solve_calls(), tokens_per_turn=11), 0)
    assert r.prompt_tokens + r.completion_tokens == 22 and r.total_tokens == 22
    assert r.agent_latency_s == pytest.approx(0.5)


class ExplodingAgent(Agent):
    name = "explode"

    def start(self, ctx: EpisodeContext) -> None:
        pass

    def act(self, observation: str) -> Action:
        raise ConnectionRefusedError("server down")


def test_agent_exceptions_propagate_and_leave_no_complete_trajectory(tmp_path):
    with pytest.raises(ConnectionRefusedError):
        run_suite(ToyEnv, ExplodingAgent, [0], 1, env_spec="toy", run_dir=tmp_path)
    assert not list(tmp_path.rglob("*.jsonl"))


class CountingOracle(ToyOracle):
    acts = 0

    def act(self, observation):
        CountingOracle.acts += 1
        return super().act(observation)


def test_run_suite_resume_skips_complete_trajectories(tmp_path):
    CountingOracle.acts = 0
    first = run_suite(ToyEnv, CountingOracle, [0, 1], 3, env_spec="toy", run_dir=tmp_path)
    ran = CountingOracle.acts
    assert len(first) == 6 and ran > 0
    skipped = []
    second = run_suite(
        ToyEnv, CountingOracle, [0, 1], 3, env_spec="toy", run_dir=tmp_path, on_trial=lambda r, s: skipped.append(s)
    )
    assert CountingOracle.acts == ran
    assert all(skipped) and [r.to_dict() for r in second] == [r.to_dict() for r in first]


def test_run_suite_resumes_after_interruption(tmp_path):
    CountingOracle.acts = 0
    run_suite(ToyEnv, CountingOracle, [0], 3, env_spec="toy", run_dir=tmp_path)
    victim = next(tmp_path.rglob("0000-01.jsonl"))
    victim.unlink()
    (victim.parent / "0000-01.jsonl.partial").write_text('{"type": "header"')  # torn write
    before = CountingOracle.acts
    seen = []
    out = run_suite(
        ToyEnv, CountingOracle, [0], 3, env_spec="toy", run_dir=tmp_path, on_trial=lambda r, s: seen.append(s)
    )
    assert seen == [True, False, True]
    assert CountingOracle.acts > before and len(out) == 3
    assert not list(tmp_path.rglob("*.partial"))


def test_resume_refuses_a_different_agent(tmp_path):
    run_suite(ToyEnv, ToyOracle, [0], 1, env_spec="toy", run_dir=tmp_path)

    class Other(ToyOracle):
        name = "other-oracle"

    with pytest.raises(ResumeError):
        run_suite(ToyEnv, Other, [0], 1, env_spec="toy", run_dir=tmp_path)


def test_resume_false_reruns(tmp_path):
    run_suite(ToyEnv, ToyOracle, [0], 1, env_spec="toy", run_dir=tmp_path)
    flags = []
    run_suite(
        ToyEnv, ToyOracle, [0], 1, env_spec="toy", run_dir=tmp_path, resume=False, on_trial=lambda r, s: flags.append(s)
    )
    assert flags == [False]


def test_run_suite_rejects_zero_trials():
    with pytest.raises(ValueError):
        run_suite(ToyEnv, ToyOracle, [0], 0, env_spec="toy")


class SeededRandomAgent(Agent):
    name = "seeded-random"

    def start(self, ctx: EpisodeContext) -> None:
        import random

        self.rng = random.Random(ctx.trial_seed)

    def act(self, observation: str) -> Action:
        from trialgauntlet.models import ToolCall

        if self.rng.random() < 0.2:
            return Action(ToolCall("finish", {"summary": ""}))
        return Action(ToolCall("add", {"n": self.rng.choice([1, 2, 3])}))


def test_seeded_determinism_across_runs():
    a = run_suite(ToyEnv, SeededRandomAgent, range(10), 4, env_spec="toy", run_seed=7)
    b = run_suite(ToyEnv, SeededRandomAgent, range(10), 4, env_spec="toy", run_seed=7)
    c = run_suite(ToyEnv, SeededRandomAgent, range(10), 4, env_spec="toy", run_seed=8)
    key = lambda rs: [(r.task_seed, r.trial, r.passed, r.steps, r.state_digest) for r in rs]  # noqa: E731
    assert key(a) == key(b)
    assert key(a) != key(c)
    assert len({r.trial_seed for r in a}) == len(a)


def test_trial_seed_is_derived_from_run_seed_env_task_trial():
    rs = run_suite(ToyEnv, ToyOracle, [3], 2, env_spec="toy", run_seed=5)
    assert [r.trial_seed for r in rs] == [derive_seed(5, "toy", 3, 0), derive_seed(5, "toy", 3, 1)]


def test_recorder_emits_header_steps_end_in_order():
    rec = MemoryRecorder()
    run_trial(ToyEnv(), ToyOracle(), 0, recorder=rec)
    types = [r["type"] for r in rec.records]
    assert types == ["header", "step", "step", "end"]
    assert rec.records[0]["initial_observation"]
    assert rec.records[-1]["result"]["passed"] is True


def test_context_given_to_agent_hides_task_metadata():
    seen = {}

    class Spy(ListAgent):
        def start(self, ctx):
            seen["ctx"] = ctx
            super().start(ctx)

    run_trial(ToyEnv(), Spy([]), 4, trial=2)
    ctx = seen["ctx"]
    assert ctx.task_seed == 4 and ctx.trial == 2 and "Toy policy" in ctx.system_prompt
    assert {t.name for t in ctx.tools} == {"add", "peek", "finish", "escalate"}
    assert not hasattr(ctx, "task") and not hasattr(ctx, "expect")
