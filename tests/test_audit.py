from __future__ import annotations

import json

import pytest

from trialgauntlet import cli
from trialgauntlet.audit import AuditReport, format_summary, format_table, judge, run_audit
from trialgauntlet.envs import make_env
from trialgauntlet.results import load_results

V = {"pass@1": 0.0, "pass@k": 0.0, "pass^k": 0.0}


@pytest.mark.parametrize(
    "agent,patch,metric,flagged",
    [
        ("noop", {"pass@1": 0.0}, "pass@1", False),
        ("noop", {"pass@1": 0.05}, "pass@1", False),  # equal to the threshold is not above it
        ("noop", {"pass@1": 0.0501}, "pass@1", True),
        ("random", {"pass@1": 0.01, "pass@k": 0.2}, "pass@1", False),
        ("random", {"pass@1": 0.01, "pass@k": 0.2}, "pass@k", True),
        ("refuse", {"pass@1": 0.3}, "pass@1", True),
        ("oracle", {"pass@1": 1.0}, "pass@1", False),
        ("oracle", {"pass@1": 0.98}, "pass@1", True),
        ("greedy", {"pass@1": 0.0}, "pass@1", False),
        ("greedy", {"pass@1": 0.2}, "pass@1", True),
    ],
)
def test_judge(agent, patch, metric, flagged):
    assert judge(agent, {**V, **patch}, 0.05, metric)[0] is flagged


def test_audit_passes_on_the_toy_family_member_that_is_sound(toy_family):
    report = run_audit(["toy"], n=3, k=2, n_boot=20)
    assert report.ok and len(report.rows) == 5
    by = {r.agent_key: r for r in report.rows}
    assert by["oracle"].pass1 == 1.0 and by["noop"].pass1 == 0.0 and by["greedy"].pass1 == 0.0
    assert by["greedy"].outcome_only > 0.5, "the shortcut reaches the outcome but is caught by the policy check"


def test_audit_flags_a_degenerate_grader(toy_family):
    report = run_audit(["leaky"], n=2, k=2, n_boot=10)
    assert not report.ok
    flagged = {r.agent_key for r in report.flags}
    assert {"noop", "random", "refuse"} <= flagged


def test_audit_flags_an_unsolvable_environment(toy_family):
    report = run_audit(["unsolvable"], n=2, k=2, n_boot=10)
    assert [r.agent_key for r in report.flags] == ["oracle"]


def test_audit_flags_a_grader_that_misses_policy_violations(toy_family):
    report = run_audit(["lax"], n=2, k=2, n_boot=10)
    assert [r.agent_key for r in report.flags] == ["greedy"]


def test_ungated_rows_do_not_fail_the_audit(toy_family):
    report = run_audit(["toy"], n=2, k=2, n_boot=10)
    run_audit(["leaky"], n=2, k=2, n_boot=10, gated=False, report=report)
    assert report.ok and any(r.flagged and not r.gated for r in report.rows)


def test_audit_validates_arguments(toy_family):
    with pytest.raises(ValueError, match="metric"):
        run_audit(["toy"], metric="pass@9")
    with pytest.raises(ValueError, match="must not exceed"):
        run_audit(["toy"], n=2, k=3)


def test_table_formats(toy_family):
    report = run_audit(["toy"], n=2, k=2, n_boot=10)
    text = format_table(report)
    assert "env" in text and "scripted-oracle" in text and "pass^2" in text
    md = format_table(report, markdown=True)
    assert md.splitlines()[1].startswith("|---") and md.count("\n") == len(report.rows) + 1
    assert format_table(report, rows=[]).count("\n") == 1
    assert format_summary(report).startswith("AUDIT PASSED")
    bad = run_audit(["leaky"], n=2, k=2, n_boot=10)
    assert format_summary(bad).startswith("AUDIT FAILED") and "leaky / no-op" in format_summary(bad)


def test_report_to_dict_is_json_serialisable(toy_family):
    report = run_audit(["toy"], n=2, k=2, n_boot=10)
    d = json.loads(json.dumps(report.to_dict()))
    assert d["ok"] is True and len(d["rows"]) == 5


def test_real_environments_pass_the_audit_and_it_is_reproducible():
    a = run_audit(["fleet", "ledger", "config"], n=3, k=2, n_boot=50)
    b = run_audit(["fleet", "ledger", "config"], n=3, k=2, n_boot=50)
    assert a.ok, format_summary(a)
    assert a.to_dict() == b.to_dict()
    for r in a.rows:
        if r.agent_key in ("noop", "refuse"):
            assert r.pass1 == 0.0
        if r.agent_key == "random":
            assert r.pass1 < 0.05


def test_naive_grader_variant_is_flagged_for_every_environment():
    report = run_audit(["fleet+naive", "ledger+naive", "config+naive"], agents=["noop", "refuse"], n=2, k=2, n_boot=10)
    assert not report.ok
    assert {r.env for r in report.flags} == {"fleet+naive", "ledger+naive", "config+naive"}
    for r in report.rows:
        share = sum(1 for t in make_env(r.env).task_specs() if t.expect == "escalate") / len(
            make_env(r.env).task_specs()
        )
        assert r.pass1 == pytest.approx(share), "do-nothing passes exactly the unsolvable share"


def test_audit_report_defaults():
    report = AuditReport(n=1, k=1, threshold=0.05, metric="pass@1", seed=0)
    assert report.ok and report.flags == []


def test_cli_audit_exit_codes_and_outputs(toy_family, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "BUILTIN_ENVS", ("toy",))
    assert cli.main(["audit", "--n", "2", "--k", "2", "--n-boot", "10", "--no-demo"]) == 0
    out = capsys.readouterr().out
    assert "AUDIT PASSED" in out and "scripted-oracle" in out
    monkeypatch.setattr(cli, "BUILTIN_ENVS", ("leaky",))
    assert cli.main(["audit", "--n", "2", "--k", "2", "--n-boot", "10", "--no-demo"]) == 1
    assert "AUDIT FAILED" in capsys.readouterr().out
    assert cli.main(["audit", "--n", "2", "--k", "2", "--n-boot", "10", "--no-demo", "--no-fail"]) == 0
    capsys.readouterr()
    assert (
        cli.main(["audit", "--n", "2", "--k", "2", "--n-boot", "10", "--no-demo", "--no-fail", "--format", "json"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_audit_threshold_changes_the_verdict(toy_family, capsys, monkeypatch):
    monkeypatch.setattr(cli, "BUILTIN_ENVS", ("leaky",))
    args = ["audit", "--n", "2", "--k", "2", "--n-boot", "10", "--no-demo", "--agents", "noop"]
    assert cli.main(args) == 1
    assert cli.main([*args, "--threshold", "1.0"]) == 0
    capsys.readouterr()


def test_cli_audit_writes_reproducible_result_files(tmp_path, capsys):
    args = [
        "audit",
        "--env",
        "config",
        "--n",
        "2",
        "--k",
        "2",
        "--n-boot",
        "20",
        "--agents",
        "noop,oracle",
        "--out-dir",
    ]
    assert cli.main([*args, str(tmp_path / "a")]) == 0
    assert cli.main([*args, str(tmp_path / "b")]) == 0
    capsys.readouterr()
    for name in ("baseline-noop.json", "baseline-oracle.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    doc = load_results(tmp_path / "a" / "baseline-oracle.json")
    assert doc["label"] == "BASELINE" and set(doc["environments"]) == {"config", "config+naive"}


@pytest.mark.parametrize(
    "argv,message",
    [
        (["audit", "--k", "9", "--n", "2"], "must not exceed"),
        (["audit", "--threshold", "2"], "between 0 and 1"),
        (["audit", "--agents", "telepathy"], "unknown baseline"),
        (["audit", "--env", "nowhere"], "unknown environment"),
        (["audit", "--env", "fleet+bogus"], "unknown environment modifier"),
    ],
)
def test_cli_audit_errors(argv, message, capsys):
    assert cli.main(argv) == 2
    assert message in capsys.readouterr().err
