from __future__ import annotations

import json

import pytest
from helpers import ListAgent, ToyEnv, tc

from trialgauntlet import cli
from trialgauntlet.agents.registry import make_baseline
from trialgauntlet.agents.wrappers import RetryAgent, looks_like_fault
from trialgauntlet.envs import make_env
from trialgauntlet.envs.faults import MAX_CONSECUTIVE, PROFILES, FaultedEnv
from trialgauntlet.harness import evaluate_env
from trialgauntlet.models import Action, ToolCall
from trialgauntlet.runner import replay_trajectory, run_trial
from trialgauntlet.trajectory import TrajectoryWriter

NAMES = ["fleet", "ledger", "config"]


def faulted(profile="transient", rate=1.0, seed=0, trial=0) -> FaultedEnv:
    env = FaultedEnv(ToyEnv(), profile, rate)
    env.reset(seed, trial)
    return env


def test_transient_fault_returns_503_and_does_not_apply():
    env = faulted("transient")
    res = env.step(ToolCall("add", {"n": 2}))
    doc = json.loads(res.observation)
    assert res.is_error and doc["status"] == 503 and doc["retryable"] is True
    assert env.inner.counter == 0


def test_timeout_fault_does_not_apply():
    env = faulted("timeout")
    res = env.step(ToolCall("add", {"n": 2}))
    assert json.loads(res.observation)["error"] == "timeout" and env.inner.counter == 0


def test_malformed_fault_truncates_reads_and_leaves_writes_alone():
    env = faulted("malformed")
    res = env.step(ToolCall("peek", {}))
    with pytest.raises(json.JSONDecodeError):
        json.loads(res.observation)
    assert res.is_error
    env.step(ToolCall("add", {"n": 2}))
    assert env.inner.counter == 2, "malformed only targets read-only calls; the write ran normally"


def test_lost_response_applies_the_write_but_reports_a_timeout():
    env = faulted("lost_response")
    res = env.step(ToolCall("add", {"n": 2}))
    assert json.loads(res.observation)["error"] == "timeout" and env.inner.counter == 2
    assert not env.step(ToolCall("peek", {})).is_error, "reads are not affected by lost_response"


def test_terminal_tools_are_never_faulted():
    env = faulted("transient")
    res = env.step(ToolCall("finish", {"summary": ""}))
    assert res.done and not res.is_error


def test_consecutive_faults_on_the_same_call_are_capped():
    env = faulted("transient", rate=1.0)
    outcomes = [env.step(ToolCall("add", {"n": 1})).is_error for _ in range(MAX_CONSECUTIVE + 1)]
    assert outcomes[:MAX_CONSECUTIVE] == [True] * MAX_CONSECUTIVE
    assert outcomes[MAX_CONSECUTIVE] is False
    assert env.inner.counter == 1, "the third attempt got through and was applied exactly once"
    assert env.extra_metrics()["faults_injected"] == MAX_CONSECUTIVE
    assert env.extra_metrics()["retries_after_fault"] >= MAX_CONSECUTIVE


def test_rate_zero_never_faults_and_rate_validation():
    env = faulted("mixed", rate=0.0)
    for _ in range(20):
        assert not env.step(ToolCall("peek", {})).is_error
    assert env.extra_metrics()["faults_injected"] == 0
    with pytest.raises(ValueError, match="between 0 and 1"):
        FaultedEnv(ToyEnv(), "mixed", 1.5)
    with pytest.raises(ValueError, match="unknown fault profile"):
        FaultedEnv(ToyEnv(), "gremlins")
    with pytest.raises(ValueError, match="needs a profile"):
        make_env("fleet+fault")


def test_spec_grammar_for_rate_and_composition():
    env = make_env("fleet+fault=mixed:0.4")
    assert isinstance(env, FaultedEnv) and env.rate == 0.4 and env.profile == "mixed"
    both = make_env("ledger+inject=exfil+fault=timeout")
    both.reset(0)
    metrics = both.extra_metrics()
    assert metrics["attack_variant"] == "exfil" and metrics["fault_profile"] == "timeout"
    assert make_env("fleet+fault=transient").rate == 0.25


def pattern(seed, trial, profile="mixed", n=30):
    env = faulted(profile, rate=0.5, seed=seed, trial=trial)
    out = []
    for i in range(n):
        out.append(env.step(ToolCall("peek", {})).is_error if i % 2 else env.step(ToolCall("add", {"n": i})).is_error)
    return out


def test_fault_pattern_is_deterministic_per_seed_and_trial_and_varies_across_trials():
    assert pattern(3, 0) == pattern(3, 0)
    assert pattern(3, 0) != pattern(3, 1)
    assert pattern(3, 0) != pattern(4, 0)


def test_mixed_profile_uses_every_kind():
    env = faulted("mixed", rate=1.0)
    for i in range(60):
        env.step(ToolCall("add", {"n": i % 7 + 1}))
        env.step(ToolCall("peek", {}))
    kinds = set(env.extra_metrics()["faults_by_kind"])
    assert kinds == {"transient", "timeout", "lost_response", "malformed"}


def test_every_profile_name_builds():
    for profile in PROFILES:
        assert make_env(f"config+fault={profile}")


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"hosts": []}', False),
        ('{"error": "timeout", "retryable": true}', True),
        ('{"error": "unknown host"}', False),
        ('{"hosts": [{"id": "web', True),
        ("", True),
        ("[1, 2]", False),
    ],
)
def test_looks_like_fault(text, expected):
    assert looks_like_fault(text) is expected


def test_retry_agent_reissues_the_call_up_to_max_attempts_then_passes_the_failure_on():
    inner = ListAgent([tc("add", n=2), tc("finish", summary="")])
    agent = RetryAgent(inner, max_attempts=2)
    agent.start(None)  # type: ignore[arg-type]
    first = agent.act('{"goal": "x"}')
    assert first.tool_call.name == "add"
    fault = '{"error":"timeout","retryable":true}'
    r1, r2 = agent.act(fault), agent.act(fault)
    assert r1.tool_call.arguments == r2.tool_call.arguments == {"n": 2} and r1.tool_call.id != r2.tool_call.id
    third = agent.act(fault)  # attempts exhausted: the failure is passed to the inner agent
    assert third.tool_call.name == "finish"
    assert agent.name == "list-retry" and agent.config()["max_attempts"] == 2


def test_retry_agent_does_not_retry_after_success():
    agent = RetryAgent(ListAgent([tc("peek"), tc("peek"), tc("finish", summary="")]))
    agent.start(None)  # type: ignore[arg-type]
    agent.act("{}")
    nxt = agent.act('{"counter": 1}')
    assert nxt.tool_call.name == "peek" and agent._attempts == 0
    assert isinstance(nxt, Action)


@pytest.mark.parametrize("name", NAMES)
def test_oracle_with_retry_recovers_from_every_profile_on_every_task(name):
    for profile in PROFILES:
        _, summary = evaluate_env(
            f"{name}+fault={profile}:0.3",
            make_baseline("oracle-retry", name),
            n=1,
            k=1,
            n_boot=10,
            include_timing=False,
        )
        assert summary["metrics"]["pass@1"]["value"] == 1.0, (name, profile)
        assert summary["extra"]["faults"]["pass_rate_given_fault"] in (1.0, None)


@pytest.mark.parametrize("name", NAMES)
def test_plain_oracle_degrades_and_pass_hat_k_exposes_the_inconsistency(name):
    _, summary = evaluate_env(
        f"{name}+fault=mixed:0.3", make_baseline("oracle", name), n=4, k=3, n_boot=20, include_timing=False
    )
    m = summary["metrics"]
    assert 0.1 < m["pass@1"]["value"] < 0.9
    assert m["pass^k"]["value"] < m["pass@1"]["value"] - 0.1, "the gap is the point of the harness"
    faults = summary["extra"]["faults"]
    assert faults["pass_rate_given_fault"] < 0.6 and faults["pass_rate_no_fault"] == 1.0
    assert faults["mean_retries_after_fault"] == 0.0


def test_lost_response_alone_does_not_hurt_an_agent_that_ignores_write_acknowledgements():
    _, summary = evaluate_env(
        "fleet+fault=lost_response", make_baseline("oracle", "fleet"), n=2, k=2, n_boot=10, include_timing=False
    )
    assert summary["metrics"]["pass@1"]["value"] == 1.0
    assert summary["extra"]["faults"]["mean_faults_injected"] > 0.1


def test_retrying_a_lost_response_is_safe_by_design():
    """The duplicate of an applied write is ignored; no collateral violation is recorded."""
    env = make_env("fleet+fault=lost_response:1.0")
    env.reset(0)
    host = env.base.target_hosts[0]
    svc = next(s for s, st in env.base.hosts[host]["services"].items() if st == "failed")
    call = ToolCall("restart_service", {"host": host, "service": svc})
    assert env.step(call).is_error and env.step(call).is_error  # two lost responses (the cap)
    assert "duplicate" in env.step(call).observation  # the third attempt gets through
    assert env.base.violations == []
    assert env.base.hosts[host]["services"][svc] == "running"


def test_faulted_trajectories_replay_identically(tmp_path):
    spec = "ledger+fault=mixed:0.4"
    for seed, trial in ((0, 0), (5, 1), (9, 2)):
        path = tmp_path / f"{seed}-{trial}.jsonl"
        run_trial(
            make_env(spec), make_baseline("oracle-retry", "ledger")(), seed, trial=trial, env_spec=spec,
            recorder=TrajectoryWriter(path),
        )  # fmt: skip
        report = replay_trajectory(path)
        assert report.ok, report.mismatches


def test_trials_of_one_task_see_different_faults():
    results = [
        run_trial(make_env("config+fault=mixed:0.4"), make_baseline("oracle", "config")(), 4, trial=t) for t in range(8)
    ]
    assert len({r.extra["faults_injected"] for r in results}) > 1
    assert 0 < sum(r.passed for r in results) < 8


def test_cli_fault_flag_prints_recovery_line(capsys):
    code = cli.main(
        [
            "run",
            "--agent",
            "oracle",
            "--env",
            "fleet",
            "--fault",
            "timeout:0.3",
            "--n",
            "2",
            "--k",
            "2",
            "--limit",
            "13",
            "--n-boot",
            "10",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "fleet+fault=timeout:0.3" in out and "faults:" in out and "pass rate when hit" in out
