"""The numbers in the documentation and the committed result files must be reproducible."""

from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path

import pytest

from trialgauntlet import cli, docgen
from trialgauntlet.results import load_results

ROOT = Path(__file__).resolve().parent.parent


def test_update_text_replaces_only_known_blocks():
    text = "a\n<!-- X:BEGIN -->\nold\n<!-- X:END -->\nb\n<!-- Y:BEGIN -->\nkeep\n<!-- Y:END -->\n"
    out = docgen.update_text(text, {"X": "new\nlines"})
    assert "new\nlines" in out and "old" not in out and "keep" in out
    assert docgen.update_text(out, {"X": "new\nlines"}) == out


def test_main_check_and_write_modes(tmp_path, capsys):
    f = tmp_path / "doc.md"
    f.write_text("<!-- A:BEGIN -->\nstale\n<!-- A:END -->")
    compute = lambda: {"A": "fresh"}  # noqa: E731
    assert docgen.main([str(f), "--check"], compute=compute) == 1
    assert "stale" in capsys.readouterr().err
    assert docgen.main([str(f)], compute=compute) == 0
    assert "fresh" in f.read_text()
    assert docgen.main([str(f), "--check"], compute=compute) == 0


def test_readme_and_suites_tables_match_a_fresh_run():
    assert docgen.main(["--check"]) == 0


def test_readme_states_that_llm_results_have_not_been_run():
    text = (ROOT / "README.md").read_text()
    assert "LLM results: NOT YET RUN" in text


def test_committed_baseline_results_are_what_the_audit_produces(tmp_path):
    assert cli.main(["audit", "--format", "json", "--out-dir", str(tmp_path), "--no-fail"]) == 0
    for name in ("noop", "random", "refuse", "oracle", "greedy"):
        fresh, committed = tmp_path / f"baseline-{name}.json", ROOT / "results" / f"baseline-{name}.json"
        assert filecmp.cmp(fresh, committed, shallow=False), (
            f"{committed.name} is stale; run scripts/regenerate_results.sh"
        )
        assert load_results(committed)["label"] == "BASELINE"


@pytest.mark.parametrize(
    "name,args",
    [
        ("suite-injection-oracle", ["--agent", "oracle", "--inject", "all", "--n", "2", "--k", "2"]),
        ("suite-injection-gullible", ["--agent", "gullible", "--inject", "all", "--n", "2", "--k", "2"]),
        ("suite-faults-oracle", ["--agent", "oracle", "--fault", "mixed:0.3", "--n", "8", "--k", "4"]),
        ("suite-faults-oracle-retry", ["--agent", "oracle-retry", "--fault", "mixed:0.3", "--n", "8", "--k", "4"]),
    ],
)
def test_committed_suite_results_are_reproducible(name, args, tmp_path, capsys):
    out = tmp_path / f"{name}.json"
    assert cli.main(["run", "--env", "all", *args, "--out", str(out)]) == 0
    capsys.readouterr()
    assert filecmp.cmp(out, ROOT / "results" / f"{name}.json", shallow=False), f"{name}.json is stale"


def test_regenerate_script_is_executable_and_lists_every_result_file():
    script = ROOT / "scripts" / "regenerate_results.sh"
    text = script.read_text()
    assert script.stat().st_mode & 0o111
    for needle in ("audit --out-dir results", "--inject all", "--fault mixed:0.3", "oracle-retry"):
        assert needle in text
    assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
    assert sys.executable
