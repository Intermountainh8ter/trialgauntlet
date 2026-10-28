"""The documentation, launch copy and packaging files must stay honest and in sync with the code."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from trialgauntlet import docgen

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()


TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".sh", ".json", ".mmd", ".svg", "", ".txt"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "runs", "report"}


def tracked_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or set(path.relative_to(ROOT).parts) & SKIP_DIRS:
            continue
        if path.suffix in TEXT_SUFFIXES and path.stat().st_size < 2_000_000:
            yield path


def test_readme_headline_claims_and_skeleton():
    # Real Qwen3 results (8B and 14B pairs, 4B stock rows) are committed; README no longer says NOT YET RUN.
    assert "LLM results: Qwen3 stock vs ablated pairs" in README
    assert "pass^k" in README and "degenerate-success audit" in README
    assert "Windows (PowerShell)" in README and "llama-server.exe" in README and "--jinja" in README
    assert "Intermountainh8ter/trialgauntlet" in README
    assert "not a general benchmark" in README
    assert "<!-- LLM:BEGIN -->" in README
    assert "qwen3-8b-stock" in README and "qwen3-8b-ablated" in README
    assert "results/qwen3-{4b,8b,14b}-{stock,ablated}-n4.json" in README


def test_readme_has_no_unfilled_generated_blocks():
    for name in ("LLM", "FACTS", "AUDIT", "DEMO", "INJECTION", "FAULTS"):
        body = re.search(rf"<!-- {name}:BEGIN -->\n(.*?)\n<!-- {name}:END -->", README, re.S)
        assert body and body.group(1).strip() not in ("", "X"), name


def test_hand_written_numbers_in_the_readme_match_the_audit():
    report = docgen.audit_report()
    by = {(r.env, r.agent): r for r in report.rows}
    for env in ("fleet", "ledger", "config"):
        pct = f"{100 * by[(env + '+naive', 'no-op')].pass1:.1f}%"
        assert pct in README, f"naive no-op score {pct} for {env} is missing from the README"
        assert by[(env, "no-op")].pass1 == 0.0 and by[(env, "always-refuse")].pass1 == 0.0
    random_fleet = by[("fleet", "random-tool")]
    assert f"{100 * random_fleet.pass1:.1f}%" in README and random_fleet.pass1 < 0.01
    assert all(r.pass1 <= 0.0075 for r in report.rows if r.gated and r.agent_key in ("noop", "random", "refuse"))
    faults = []
    for env in ("fleet", "ledger", "config"):
        doc = json.loads((ROOT / "results" / "suite-faults-oracle.json").read_text())
        m = doc["environments"][f"{env}+fault=mixed:0.3"]["metrics"]
        faults.append((m["pass@1"]["value"], m["pass^k"]["value"]))
    assert f"pass@1 of {100 * min(f[0] for f in faults):.0f} to {100 * max(f[0] for f in faults):.0f}%" in README
    assert f"pass^4 of {100 * min(f[1] for f in faults):.0f} to {100 * max(f[1] for f in faults):.0f}%" in README


def test_readme_relative_links_resolve():
    for target in re.findall(r"\]\((?!https?://|#)([^)#]+)", README):
        assert (ROOT / target).exists(), f"README links to missing {target}"
    assert (ROOT / "docs" / "diagrams" / "usage.svg").exists()


def test_flowcharts_embed_the_mermaid_sources_exactly_and_the_svgs_are_well_formed():
    text = (ROOT / "docs" / "FLOWCHARTS.md").read_text()
    blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.S)
    assert len(blocks) == 2
    for name, block in zip(("usage", "troubleshooting"), blocks):
        assert block == (ROOT / "docs" / "diagrams" / f"{name}.mmd").read_text().rstrip()
        root = ET.fromstring((ROOT / "docs" / "diagrams" / f"{name}.svg").read_text())
        assert root.tag.endswith("svg")
    assert (ROOT / "scripts" / "render_diagrams.sh").stat().st_mode & 0o111


def test_troubleshooting_chart_covers_the_real_symptoms_with_concrete_fixes():
    src = (ROOT / "docs" / "diagrams" / "troubleshooting.mmd").read_text()
    for symptom in (
        "audit prints FLAG", "pass^k far below pass@1", "tool calls appear as text", "replay says MISMATCH",
        "terminated: budget", "injection attack success high", "connection refused", "ResumeError",
    ):  # fmt: skip
        assert symptom in src, symptom
    for fix in ("--jinja", "trialgauntlet doctor", "--run-dir", "--max-steps", "--parse-text-tools", "rng_for"):
        assert fix in src, fix
    leaves = re.findall(r"class C1,C2.*", src)
    assert leaves and src.count("-->") >= 30
    usage = (ROOT / "docs" / "diagrams" / "usage.mmd").read_text()
    for step in (
        "pip install -e .",
        "trialgauntlet audit",
        "trialgauntlet doctor",
        "--n 8 --k 4",
        "trialgauntlet report",
    ):
        assert step in usage, step


LAUNCH_FILES = ("LINKEDIN.md", "X_THREAD.md", "DISCORD_SHORT.md", "FAQ.md")
REPO_LINK = "https://github.com/Intermountainh8ter/trialgauntlet"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _real_llm_results() -> list[dict]:
    docs = [json.loads(p.read_text()) for p in sorted((ROOT / "results").glob("*.json"))]
    return [d for d in docs if d.get("label") == "REAL"]


def _figures_derivable_from_results() -> dict[str, set[str]]:
    """Every LLM figure the docs may quote, recomputed from results/*.json (never from the README).

    `pct` holds point estimates only. Interval bounds (`ci`) and per-cell `violation_rate` are returned separately: the
    launch copy quotes neither, and the README's dated correction is about quoting a per-cell violation rate as a
    benchmark-wide one, so only the README's own prose may use them.
    """
    pct: set[str] = set()
    ci: set[str] = set()
    two_decimals: set[str] = set()
    counts: set[str] = set()
    cell_violation_rates: set[str] = set()
    for doc in _real_llm_results():
        trials = viol = share = misuse = no_action = tool_calls = 0.0
        for summary in doc["environments"].values():
            for metric in summary["metrics"].values():
                pct.add(_pct(metric["value"]))
                ci.update(_pct(bound) for bound in metric.get("ci", ()))
            n_trials, rel = summary["trials"], summary["reliability"]
            trials += n_trials
            viol += rel["mean_policy_violations"] * n_trials
            share += rel["violation_rate"] * n_trials
            misuse += rel["mean_tool_misuse"] * n_trials
            no_action += summary["terminated"].get("no_action", 0)
            tool_calls += round(summary["usage"]["mean_steps"] * n_trials)
            two_decimals.update(f"{rel[k]:.2f}" for k in ("mean_policy_violations", "mean_tool_misuse"))
            cell_violation_rates.add(_pct(rel["violation_rate"]))
        pct.add(_pct(share / trials))
        two_decimals.update((f"{viol / trials:.2f}", f"{misuse / trials:.2f}"))
        counts.update((str(int(no_action)), str(int(tool_calls))))
    # figures about the scripted baselines come from the README's generated audit and demo tables
    for name in ("AUDIT", "DEMO"):
        body = re.search(rf"<!-- {name}:BEGIN -->\n(.*?)\n<!-- {name}:END -->", README, re.S).group(1)
        pct.update(re.findall(r"\d+\.\d%", body))
    return {"pct": pct, "ci": ci, "two": two_decimals, "counts": counts, "rates": cell_violation_rates}


def _unverifiable_figures(text: str, readme_prose: bool = False) -> list[str]:
    """Quoted figures in `text` that cannot be recomputed from the committed result files.

    "N.N points" must equal a `gap` cell (pass@1 minus pass^k). With `readme_prose` the README's own extras are
    allowed: interval bounds, the per-cell violation rate in the correction note, and differences between two cells
    ("roughly 9.6 pp"), which are arithmetic on table cells rather than table cells.
    """
    known = _figures_derivable_from_results()
    pct = known["pct"] | (known["ci"] | known["rates"] if readme_prose else set())
    text = re.sub(r"python 3\.\d+\+?", "", text, flags=re.I)  # a version number is not a figure
    bad = [m for m in re.findall(r"(?<![\d.])\d+\.\d%", text) if m not in pct]
    bad += [m for m in re.findall(r"(?<![\d.])\d+\.\d\d(?!\d)", text) if m not in known["two"]]
    if not readme_prose:
        bad += [f"{m}%" for m in re.findall(r"(\d+\.\d) (?:points|pp)\b", text) if f"{m}%" not in pct]
    bad += [m for m in re.findall(r"\b(\d+) (?:of|/) ?552\b", text) if m not in known["counts"]]
    bad += [m for m in re.findall(r"\b(\d+) (?:parsed|tool) calls?\b", text) if m not in known["counts"]]
    return bad


def test_launch_copy_exists_respects_length_limits_and_reports_the_real_llm_results():
    d = ROOT / "docs" / "launch"
    assert {p.name for p in d.iterdir()} >= set(LAUNCH_FILES)
    thread = (d / "X_THREAD.md").read_text().split("---\n", 1)[1]
    posts = [p.strip() for p in re.split(r"\n\n(?=\d/ )", thread.strip())]
    assert len(posts) == 7
    for post in posts:
        assert len(post.replace("\n", " ")) <= 280, (len(post), post[:60])
    assert REPO_LINK in posts[-1]
    discord = (d / "DISCORD_SHORT.md").read_text().split("---\n", 1)[1].strip()
    assert len(discord) <= 800 and REPO_LINK in discord
    linkedin = (d / "LINKEDIN.md").read_text()
    assert len(linkedin.split("---\n", 1)[1].strip()) <= 3000
    assert REPO_LINK in linkedin.strip().splitlines()[-1]
    for name in LAUNCH_FILES:
        text = (d / name).read_text().lower()
        assert "<repo link>" not in text, name
        # real results exist now, so the pre-run disclaimers would be false; the limits must be stated instead
        assert not re.search(r"not yet run|no real llm|no claim about real llm|none yet", text), name
        assert "qwen3" in text and "n=4" in text, f"{name} must say which model family and how many trials"
        for forbidden in (
            "outperform",
            "beats gpt",
            "state of the art",
            "state-of-the-art",
            "sota",
            "leaderboard topping",
        ):
            assert forbidden not in text, (name, forbidden)
        assert not re.search(r"(qwen|llama|mistral|gemma)[\w\-. ]{0,30}(scores|scored|achieves|achieved)", text), name


def test_launch_copy_states_what_the_real_runs_do_not_show():
    d = ROOT / "docs" / "launch"
    for name in ("LINKEDIN.md", "FAQ.md"):
        text = (d / name).read_text().lower()
        for limit in ("synthetic", "keyword rules", "same person", "one machine", "one model family", "overlap"):
            assert limit in text, (name, limit)
    for name in ("X_THREAD.md", "DISCORD_SHORT.md"):
        text = (d / name).read_text().lower()
        assert "noisy" in text and "one machine" in text, name
    faq = (d / "FAQ.md").read_text()
    assert "format artefact" in faq and "373 of 552" in faq and "no_action" in faq
    assert faq.rstrip().endswith(
        "**Was AI used to build this?** Yes. An AI coding assistant wrote most of the code, tests and prose in this "
        "repository (the commits are co-authored in the git history). I directed the work and ran the real-model "
        "benchmarks on my own hardware. Every number in the README is generated by a script from committed result "
        "files, and the tests fail if they drift. Read the code and the methodology before trusting any conclusion."
    )


@pytest.mark.parametrize("name", LAUNCH_FILES)
def test_every_llm_figure_in_the_launch_copy_is_recomputable_from_the_result_files(name):
    text = (ROOT / "docs" / "launch" / name).read_text()
    assert _unverifiable_figures(text) == []
    # the figures the copy leans on are really there, so the check above is not passing on an empty set
    assert "55.3%" in _figures_derivable_from_results()["pct"] and "0.60" in _figures_derivable_from_results()["two"]


def _value(arm: str, env: str, metric: str) -> float:
    doc = json.loads((ROOT / "results" / f"{arm}-n4.json").read_text())
    return doc["environments"][env]["metrics"][metric]["value"]


def _cell(arm: str, env: str, metric: str) -> str:
    return _pct(_value(arm, env, metric))


def test_headline_cells_are_quoted_with_the_value_the_result_file_holds():
    """The generic check above accepts any real figure; this one binds the headline claims to their own cells."""
    d = ROOT / "docs" / "launch"
    eight = [
        ("qwen3-8b-stock", "fleet", "pass@1"), ("qwen3-8b-stock", "fleet", "pass^k"),
        ("qwen3-8b-ablated", "fleet", "pass@1"), ("qwen3-8b-stock", "ledger", "pass@1"),
        ("qwen3-8b-stock", "ledger", "pass^k"), ("qwen3-8b-ablated", "ledger", "pass@1"),
        ("qwen3-8b-stock", "config", "pass@1"), ("qwen3-8b-ablated", "config", "pass@1"),
        ("qwen3-8b-stock", "config", "pass^k"), ("qwen3-8b-ablated", "config", "pass^k"),
    ]  # fmt: skip
    fourteen = [
        ("qwen3-14b-stock", "ledger", "pass@1"), ("qwen3-14b-ablated", "ledger", "pass@1"),
        ("qwen3-14b-stock", "config", "pass@1"), ("qwen3-14b-ablated", "config", "pass@1"),
        ("qwen3-14b-stock", "fleet", "pass@1"),
    ]  # fmt: skip
    envs = ("fleet", "ledger", "config")
    native = [("qwen3-4b-stock-native", env, "pass@1") for env in envs]
    gaps = [_value(f"qwen3-14b-{arm}", env, "gap") for arm in ("stock", "ablated") for env in envs]
    gap_range = f"{100 * min(gaps):.1f} to {100 * max(gaps):.1f} points"
    wanted = {
        "X_THREAD.md": eight + fourteen + native,
        "LINKEDIN.md": eight + fourteen + native,
        "FAQ.md": eight + fourteen + native,
        "DISCORD_SHORT.md": [
            ("qwen3-8b-stock", "fleet", "pass@1"), ("qwen3-8b-stock", "fleet", "pass^k"),
            ("qwen3-8b-stock", "config", "pass@1"), ("qwen3-8b-ablated", "config", "pass@1"),
        ],
    }  # fmt: skip
    for name, cells in wanted.items():
        text = (d / name).read_text()
        for arm, env, metric in cells:
            assert _cell(arm, env, metric) in text, (name, arm, env, metric, _cell(arm, env, metric))
        if name != "DISCORD_SHORT.md":
            assert gap_range in text, (name, gap_range)


def test_the_figure_check_rejects_invented_and_misattributed_numbers():
    bad = _unverifiable_figures(
        "qwen3-8b-stock hit 88.8% pass@1 with 0.11 violations per trial, 14.0 points of gap, and 99 of 552 trials "
        "ended in no_action; the overall violation rate was 20.4%."
    )
    assert set(bad) == {"88.8%", "0.11", "14.0%", "99", "20.4%"}
    # 20.4% is a real per-cell figure, usable only where the README explains why it is not benchmark-wide
    assert _unverifiable_figures("the config share was 20.4%", readme_prose=True) == []


def test_llm_figures_in_the_readme_prose_are_recomputable_from_the_result_files():
    section = README.split("## LLM results", 1)[1].split("Everything below is for the built-in", 1)[0]
    assert _unverifiable_figures(section, readme_prose=True) == []
    # outside the dated correction note, a per-cell violation rate may not appear as a benchmark-wide figure
    outside = re.sub(r"> \*\*Correction.*?\n\n", "", section, flags=re.S)
    known = _figures_derivable_from_results()
    assert not (set(re.findall(r"\d+\.\d%", outside)) & (known["rates"] - known["pct"] - known["ci"]))


def test_no_placeholders_and_no_ai_model_identifiers_in_the_repository():
    banned = re.compile(r"\b(claude|anthropic|chatgpt|gpt-\d|sonnet|opus|haiku|gemini)\b", re.I)
    todo = re.compile(r"\b(TODO|FIXME|XXX|TBD)\b")
    self_path = Path(__file__).resolve()
    for path in tracked_text_files():
        if path.resolve() == self_path or path.suffix == ".svg":
            continue
        text = path.read_text(errors="ignore")
        assert not banned.search(text), f"model identifier in {path.relative_to(ROOT)}"
        if path.suffix in {".py", ".md", ".sh", ".yml", ".toml"}:
            assert not todo.search(text), f"placeholder marker in {path.relative_to(ROOT)}"


def test_license_and_packaging_metadata():
    assert "Copyright (c) 2026 Ammon Jackson" in (ROOT / "LICENSE").read_text()
    pyproject = (ROOT / "pyproject.toml").read_text()
    for needle in (
        'name = "trialgauntlet"',
        'trialgauntlet = "trialgauntlet.cli:main"',
        "pytest-cov",
        'requires-python = ">=3.10"',
    ):
        assert needle in pyproject


def test_makefile_dockerfile_and_ci_gate_the_right_things():
    make = (ROOT / "Makefile").read_text()
    for target in (
        "install:",
        "lint:",
        "test:",
        "cov:",
        "audit:",
        "baselines:",
        "docs-check:",
        "diagrams:",
        "docker:",
        "check:",
    ):
        assert target in make
    docker = (ROOT / "Dockerfile").read_text()
    assert "ENTRYPOINT" in docker and "trialgauntlet" in docker and "pip install" in docker
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for needle in ('"3.10"', '"3.11"', '"3.12"', '"3.13"', "ruff check .", "pytest -q --cov", "--cov-fail-under=90",
                   "trialgauntlet audit", "docgen --check", "git diff --exit-code results"):  # fmt: skip
        assert needle in ci, needle


def test_contributing_requires_the_audit_and_changelog_exists():
    text = (ROOT / "CONTRIBUTING.md").read_text()
    assert (
        "trialgauntlet audit" in text
        and "do not raise" in text
        and "BaseEnv" in text
        and "docs/ENVIRONMENTS.md" in text
    )
    assert "## 0.1.0" in (ROOT / "CHANGELOG.md").read_text()


def test_threats_document_covers_the_required_limitations():
    text = (ROOT / "docs" / "THREATS_TO_VALIDITY.md").read_text().lower()
    for needle in (
        "small", "scripted users are unrealistic", "graders encode", "baseline",
        "qwen3", "n=4", "one machine", "overlap", "same author",
    ):  # fmt: skip
        assert needle in text, needle
    assert "no real llm has been run" not in text, "real Qwen3 results are committed; the statement would be false"


@pytest.mark.parametrize("name", ["METHODOLOGY", "ENVIRONMENTS", "SUITES", "THREATS_TO_VALIDITY", "FLOWCHARTS"])
def test_docs_exist_and_are_not_stubs(name):
    assert len((ROOT / "docs" / f"{name}.md").read_text()) > 1500
