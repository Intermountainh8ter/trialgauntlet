from __future__ import annotations

from helpers import ToyEnv, ToyOracle

from trialgauntlet import cli
from trialgauntlet.runner import run_suite
from trialgauntlet.trajectory import trajectory_path


def test_replay_command_reports_identical(tmp_path, capsys, toy_registered):
    run_suite(ToyEnv, ToyOracle, [0, 4], 1, env_spec="toy", run_dir=tmp_path)
    assert cli.main(["replay", str(tmp_path), "--verbose"]) == 0
    out = capsys.readouterr().out
    assert out.count("IDENTICAL") == 2 and "2/2" in out
    assert cli.main(["replay", str(tmp_path)]) == 0
    quiet = capsys.readouterr().out
    assert "IDENTICAL" not in quiet and "2/2 trajectories replay to the identical grade" in quiet


def test_replay_command_flags_mismatch(tmp_path, capsys, toy_registered):
    run_suite(ToyEnv, ToyOracle, [0], 1, env_spec="toy", run_dir=tmp_path)
    path = trajectory_path(tmp_path, "toy", 0, 0)
    path.write_text(path.read_text().replace('"n": 2', '"n": 3'))
    assert cli.main(["replay", str(path)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_replay_command_errors(tmp_path, capsys, toy_registered):
    assert cli.main(["replay", str(tmp_path / "nope")]) == 2
    assert "no such file" in capsys.readouterr().err
    assert cli.main(["replay", str(tmp_path)]) == 2
    bad = tmp_path / "bad.jsonl"
    bad.write_text("garbage\n")
    assert cli.main(["replay", str(bad)]) == 1
    assert "ERROR" in capsys.readouterr().out


def test_replay_unknown_environment_is_reported(tmp_path, capsys, toy_registered):
    run_suite(ToyEnv, ToyOracle, [0], 1, env_spec="toy", run_dir=tmp_path)
    path = trajectory_path(tmp_path, "toy", 0, 0)
    path.write_text(path.read_text().replace('"env": "toy"', '"env": "ghost"'))
    assert cli.main(["replay", str(path)]) == 1
    assert "unknown environment" in capsys.readouterr().out
