from __future__ import annotations

import json

import pytest
from helpers import ListAgent, ToyEnv, ToyOracle, tc

from trialgauntlet.budget import Budget
from trialgauntlet.runner import ReplayAgent, replay_trajectory, run_suite, run_trial
from trialgauntlet.trajectory import (
    TrajectoryError,
    TrajectoryWriter,
    is_complete,
    read_trajectory,
    trajectory_path,
)


@pytest.fixture
def recorded(tmp_path, toy_registered):
    run_suite(ToyEnv, ToyOracle, [0, 4], 2, env_spec="toy", run_dir=tmp_path)
    return tmp_path


def test_files_are_named_by_env_seed_trial(recorded):
    p = trajectory_path(recorded, "toy", 4, 1)
    assert p.exists() and p.name == "0004-01.jsonl"
    assert not list(recorded.rglob("*.partial"))


def test_env_spec_with_plus_is_sanitised(tmp_path):
    p = trajectory_path(tmp_path, "fleet+inject=x", 3, 0)
    assert "+" not in str(p.parent.name)


def test_read_back_matches_result(recorded):
    traj = read_trajectory(trajectory_path(recorded, "toy", 0, 0))
    assert traj.header["agent"]["name"] == "toy-oracle"
    assert [s["action"]["tool_call"]["name"] for s in traj.steps] == ["add", "finish"]
    assert traj.result().passed
    assert traj.end["terminated"] == "finish"


def test_replay_reproduces_identical_grade(recorded):
    for seed in (0, 4):
        report = replay_trajectory(trajectory_path(recorded, "toy", seed, 0))
        assert report.ok, report.mismatches
        assert report.replayed.passed and report.replayed.state_digest == report.original.state_digest


def test_replay_of_noop_with_nudge_and_format_errors(tmp_path, toy_registered):
    for name, agent in {
        "noop": ListAgent([]),
        "fmt": ListAgent([None, None, tc("add", n=2), tc("finish", summary="")], format_error="tool_call_as_text"),
    }.items():
        rec = TrajectoryWriter(tmp_path / f"{name}.jsonl")
        run_trial(ToyEnv(), agent, 0, env_spec="toy", recorder=rec)
        assert replay_trajectory(tmp_path / f"{name}.jsonl").ok


def test_replay_of_budget_terminated_runs(tmp_path, toy_registered):
    rec = TrajectoryWriter(tmp_path / "a.jsonl")
    run_trial(ToyEnv(), ListAgent([tc("peek")] * 5), 0, env_spec="toy", recorder=rec, budget=Budget(max_steps=3))
    assert replay_trajectory(tmp_path / "a.jsonl").ok
    rec = TrajectoryWriter(tmp_path / "b.jsonl")
    run_trial(ToyEnv(), ListAgent(solve := [tc("add", n=2), tc("finish", summary="")], tokens_per_turn=100), 0,
              env_spec="toy", recorder=rec, budget=Budget(max_tokens=150))  # fmt: skip
    assert solve and replay_trajectory(tmp_path / "b.jsonl").ok


def test_replay_of_time_budget_trajectory_uses_forced_termination(tmp_path, toy_registered):
    ticks = iter(range(0, 1000))
    rec = TrajectoryWriter(tmp_path / "t.jsonl")
    r = run_trial(
        ToyEnv(), ListAgent([tc("peek")] * 9), 0, env_spec="toy", recorder=rec,
        budget=Budget(max_seconds=4), clock=lambda: float(next(ticks)),
    )  # fmt: skip
    assert r.terminated == "budget:time"
    report = replay_trajectory(tmp_path / "t.jsonl")
    assert report.ok, report.mismatches


def edit_jsonl(path, fn):
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    fn(lines)
    path.write_text("\n".join(json.dumps(x, sort_keys=True) for x in lines) + "\n")


def test_replay_detects_tampered_observation(recorded):
    path = trajectory_path(recorded, "toy", 0, 0)

    def tamper(lines):
        lines[1]["observation"] = '{"counter":999}'

    edit_jsonl(path, tamper)
    report = replay_trajectory(path)
    assert not report.ok and any("observation" in m for m in report.mismatches)


def test_replay_detects_tampered_recorded_grade(recorded):
    path = trajectory_path(recorded, "toy", 0, 0)

    def tamper(lines):
        lines[-1]["result"]["passed"] = False

    edit_jsonl(path, tamper)
    report = replay_trajectory(path)
    assert not report.ok and any("passed" in m for m in report.mismatches)


def test_replay_detects_tampered_action(recorded):
    path = trajectory_path(recorded, "toy", 0, 0)

    def tamper(lines):
        lines[1]["action"]["tool_call"]["arguments"]["n"] = 5

    edit_jsonl(path, tamper)
    assert not replay_trajectory(path).ok


def test_replay_detects_nondeterministic_environment(recorded, monkeypatch):
    path = trajectory_path(recorded, "toy", 0, 0)
    orig = ToyEnv._t_add

    def drifting(self, n):
        return orig(self, n + 1)

    monkeypatch.setattr(ToyEnv, "_t_add", drifting)
    report = replay_trajectory(path)
    assert not report.ok and any("digest" in m or "observation" in m for m in report.mismatches)


def test_replay_agent_returns_empty_action_when_exhausted():
    agent = ReplayAgent([])
    agent.start(None)  # type: ignore[arg-type]
    assert agent.act("x").tool_call is None


def test_read_errors(tmp_path):
    with pytest.raises(TrajectoryError, match="cannot read"):
        read_trajectory(tmp_path / "missing.jsonl")
    p = tmp_path / "x.jsonl"
    p.write_text("not json\n")
    with pytest.raises(TrajectoryError, match="invalid JSON"):
        read_trajectory(p)
    p.write_text('{"type":"mystery"}\n')
    with pytest.raises(TrajectoryError, match="unknown record"):
        read_trajectory(p)
    p.write_text('{"type":"step"}\n')
    with pytest.raises(TrajectoryError, match="missing header"):
        read_trajectory(p)
    p.write_text('{"type":"header","schema":1}\n\n')
    with pytest.raises(TrajectoryError, match="incomplete"):
        read_trajectory(p)
    p.write_text('{"type":"header","schema":99}\n{"type":"end"}\n')
    with pytest.raises(TrajectoryError, match="unsupported schema"):
        read_trajectory(p)
    assert not is_complete(p)


def test_writer_commit_is_atomic(tmp_path):
    w = TrajectoryWriter(tmp_path / "sub" / "t.jsonl")
    w.write({"type": "header"})
    assert (tmp_path / "sub" / "t.jsonl.partial").exists() and not (tmp_path / "sub" / "t.jsonl").exists()
    w.close()
    assert (tmp_path / "sub" / "t.jsonl").exists() and not (tmp_path / "sub" / "t.jsonl.partial").exists()


def test_writer_close_without_write_raises_and_abort_is_safe(tmp_path):
    w = TrajectoryWriter(tmp_path / "t.jsonl")
    with pytest.raises(TrajectoryError):
        w.close()
    w.abort()
    w.write({"type": "header"})
    w.abort()
    assert not (tmp_path / "t.jsonl").exists()
