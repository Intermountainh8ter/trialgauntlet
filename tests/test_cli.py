from __future__ import annotations

import json

import pytest

from trialgauntlet import cli
from trialgauntlet.harness import evaluate_env, select_seeds
from trialgauntlet.results import load_results


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for name in ("list", "run", "audit", "replay"):
        assert name in out


def test_list_describes_every_environment(capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "fleet: 52 tasks" in out and "ledger: 42 tasks" in out and "config: 44 tasks" in out
    assert "esc_sole_copy" in out and "escalate" in out
    assert cli.main(["list", "--env", "fleet+naive"]) == 0


def test_select_seeds_filters():
    assert len(select_seeds("fleet")) == 52
    t1 = select_seeds("fleet", tiers=["T1"])
    assert t1 and all(s % 13 in (0, 1, 2, 3) for s in t1)
    assert select_seeds("ledger", kinds=["simple_refund"]) == [0, 14, 28]
    assert select_seeds("config", limit=5) == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError, match="no tasks"):
        select_seeds("fleet", kinds=["nonexistent"])


def test_evaluate_env_rejects_k_greater_than_n():
    from trialgauntlet.agents.registry import make_baseline

    with pytest.raises(ValueError, match="at least k trials"):
        evaluate_env("fleet", make_baseline("noop", "fleet"), n=2, k=3)


def test_run_prints_summary_and_writes_results(tmp_path, capsys):
    out = tmp_path / "r.json"
    code = cli.main(
        [
            "run",
            "--agent",
            "oracle",
            "--env",
            "config",
            "--n",
            "2",
            "--k",
            "2",
            "--limit",
            "6",
            "--n-boot",
            "20",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "config: 6 tasks x n=2 trials" in text and "pass^2" in text and "wrote" in text
    doc = load_results(out)
    assert doc["agent"]["name"] == "scripted-oracle" and doc["environments"]["config"]["tasks"] == 6


def test_run_with_tier_filter_and_run_dir_is_resumable(tmp_path, capsys):
    args = ["run", "--agent", "greedy", "--env", "ledger", "--n", "2", "--k", "2", "--tiers", "T1", "--n-boot", "10"]
    assert cli.main([*args, "--run-dir", str(tmp_path)]) == 0
    first = capsys.readouterr().out
    n_files = len(list(tmp_path.rglob("*.jsonl")))
    assert n_files == 2 * 12  # 12 T1 tasks x 2 trials
    assert cli.main([*args, "--run-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == first
    assert cli.main(["replay", str(tmp_path)]) == 0


def test_run_resume_detects_a_different_agent(tmp_path, capsys):
    base = [
        "run",
        "--env",
        "config",
        "--n",
        "1",
        "--k",
        "1",
        "--limit",
        "3",
        "--n-boot",
        "10",
        "--run-dir",
        str(tmp_path),
    ]
    assert cli.main([*base, "--agent", "oracle"]) == 0
    from trialgauntlet.runner import ResumeError

    with pytest.raises(ResumeError):
        cli.main([*base, "--agent", "greedy"])
    capsys.readouterr()


def test_run_max_steps_budget_changes_outcomes(capsys):
    code = cli.main(
        [
            "run",
            "--agent",
            "oracle",
            "--env",
            "fleet",
            "--n",
            "1",
            "--k",
            "1",
            "--limit",
            "13",
            "--max-steps",
            "2",
            "--n-boot",
            "10",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "budget:steps" in out and "pass@1     " in out


@pytest.mark.parametrize(
    "argv,message",
    [
        (["run", "--agent", "telepathy"], "unknown agent"),
        (["run", "--k", "9", "--n", "2"], "must not exceed"),
        (["run", "--env", "nowhere"], "unknown environment"),
        (["run", "--env", "fleet", "--kinds", "nothing"], "no tasks"),
        (["run", "--env", ","], "no environments"),
        (["replay"], None),
    ],
)
def test_cli_errors(argv, message, capsys):
    if message is None:
        with pytest.raises(SystemExit):
            cli.main(argv)
        return
    assert cli.main(argv) == 2
    assert message in capsys.readouterr().err


def test_cli_run_json_is_valid_for_naive_variant(tmp_path, capsys):
    out = tmp_path / "n.json"
    cli.main(
        ["run", "--agent", "noop", "--env", "ledger+naive", "--n", "2", "--k", "2", "--n-boot", "10", "--out", str(out)]
    )
    capsys.readouterr()
    doc = json.loads(out.read_text())
    assert doc["environments"]["ledger+naive"]["metrics"]["pass@1"]["value"] == pytest.approx(5 / 14, abs=1e-6)
