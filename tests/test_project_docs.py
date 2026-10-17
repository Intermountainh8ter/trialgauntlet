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
    # Qwen3-8B pair results are now committed; README no longer says NOT YET RUN.
    assert "LLM results: Qwen3-8B stock vs ablated pair" in README
    assert "pass^k" in README and "degenerate-success audit" in README
    assert "Windows (PowerShell)" in README and "llama-server.exe" in README and "--jinja" in README
    assert "Intermountainh8ter/trialgauntlet" in README
    assert "not a general benchmark" in README
    assert "<!-- LLM:BEGIN -->" in README
    assert "qwen3-8b-stock" in README and "qwen3-8b-ablated" in README
    assert "results/qwen3-8b-{stock,ablated}-n4.json" in README


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


def test_launch_copy_exists_respects_length_limits_and_claims_no_llm_results():
    d = ROOT / "docs" / "launch"
    assert {p.name for p in d.iterdir()} >= {"LINKEDIN.md", "X_THREAD.md", "DISCORD_SHORT.md", "FAQ.md"}
    thread = (d / "X_THREAD.md").read_text().split("---\n", 1)[1]
    posts = [p.strip() for p in re.split(r"\n\n(?=\d/ )", thread.strip())]
    assert len(posts) == 7
    for post in posts:
        assert len(post.replace("\n", " ")) <= 280, (len(post), post[:60])
    discord = (d / "DISCORD_SHORT.md").read_text().split("---\n", 1)[1].strip()
    assert len(discord) <= 800
    for name in ("LINKEDIN.md", "X_THREAD.md", "DISCORD_SHORT.md", "FAQ.md"):
        text = (d / name).read_text().lower()
        assert re.search(r"no real llm|not yet run|no claim about real llm", text), f"{name} must disclaim LLM results"
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
    for needle in ("small", "scripted users are unrealistic", "graders encode", "baseline", "no real llm"):
        assert needle in text, needle


@pytest.mark.parametrize("name", ["METHODOLOGY", "ENVIRONMENTS", "SUITES", "THREATS_TO_VALIDITY", "FLOWCHARTS"])
def test_docs_exist_and_are_not_stubs(name):
    assert len((ROOT / "docs" / f"{name}.md").read_text()) > 1500
