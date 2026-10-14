from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from trialgauntlet import cli
from trialgauntlet.agents.llm import LLMAgent, LLMConfig
from trialgauntlet.harness import evaluate_env
from trialgauntlet.leaderboard import (
    ENTRY_FIELDS,
    LEADERBOARD_SCHEMA,
    LeaderboardError,
    build_leaderboard,
    load_leaderboard,
    validate_leaderboard,
)
from trialgauntlet.mockserver import MockServer
from trialgauntlet.report import (
    ReportError,
    audit_rows,
    classify,
    collect,
    gap_rows,
    render_markdown,
    svg_audit_chart,
    svg_gap_chart,
    write_report,
)
from trialgauntlet.results import build_results, load_results, write_results

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


@pytest.fixture(scope="module")
def mock_doc():
    with MockServer("flaky", flaky=0.06) as server:
        cfg = LLMConfig(base_url=server.url, model="example-model", temperature=0.7)
        _, summary = evaluate_env("config", lambda: LLMAgent(cfg), n=4, k=3, seeds=list(range(0, 44, 4)), n_boot=50)
    return build_results(
        agent={
            "name": "example-model",
            "id": "x",
            "type": "llm",
            "model": "example-model",
            "temperature": 0.7,
            "config": {},
        },
        label="MOCK",
        summaries={"config": summary},
        run={"n": 4, "k": 3, "seed": 0, "n_boot": 50},
    )


@pytest.fixture
def real_doc(mock_doc):
    doc = copy.deepcopy(mock_doc)
    doc["label"] = "REAL"  # test fixture only: pretend the server was real in order to exercise rendering
    return doc


def entries_for(*docs, names=None):
    return [(Path(f"{i}.json"), d) for i, d in enumerate(docs)]


def baseline_entries():
    return collect([RESULTS])


def test_report_refuses_when_there_are_no_results(tmp_path):
    with pytest.raises(ReportError, match="refusing to render"):
        collect([tmp_path])
    with pytest.raises(ReportError, match="no such file"):
        collect([tmp_path / "missing"])


def test_report_refuses_invalid_results(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({"schema": "nope"}))
    with pytest.raises(ReportError, match="bad.json"):
        collect([tmp_path])


def test_cli_report_refuses_with_exit_status_2(tmp_path, capsys):
    assert cli.main(["report", str(tmp_path), "--out-dir", str(tmp_path / "out")]) == 2
    assert "refusing to render" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_baseline_only_report_says_llm_results_not_yet_run():
    md = render_markdown(baseline_entries())
    assert "LLM results: NOT YET RUN" in md
    assert "## Baseline agents" in md and "## Degenerate-success audit" in md and "AUDIT PASSED" in md
    assert "## Injection suite" in md and "## Fault suite" in md
    assert "MOCK" not in md


def test_mock_runs_are_quarantined_in_their_own_section(mock_doc):
    md = render_markdown(entries_for(mock_doc))
    assert "LLM results: NOT YET RUN" in md and "## MOCK runs (plumbing only)" in md
    assert "say nothing about any model" in md and "example-model" in md
    assert classify(mock_doc) == "mock"


def test_real_llm_runs_get_the_llm_section_and_no_not_yet_run_banner(real_doc):
    md = render_markdown(entries_for(real_doc))
    assert "LLM results: NOT YET RUN" not in md and "## MOCK runs" not in md
    assert "### example-model  (n=4, k=3, temperature 0.7)" in md and "By slice:" in md
    assert "unsolvable subset (must escalate)" in md
    assert classify(real_doc) == "real"


def test_audit_rows_flag_only_above_threshold_and_mark_demo_rows():
    rows = audit_rows([d for _, d in baseline_entries()], 0.05)
    assert len(rows) == 18 and sum(r["demo"] for r in rows) == 9
    assert not any(r["flag"] for r in rows if not r["demo"])
    assert all(r["flag"] for r in rows if r["demo"] and r["agent"] in ("no-op", "always-refuse"))
    strict = audit_rows([d for _, d in baseline_entries()], 0.0)
    assert any(r["flag"] for r in strict if not r["demo"]), "random-tool is above 0%"


def parse(svg: str):
    return ET.fromstring(svg)


def texts(root):
    return [t.text or "" for t in root.iter("{http://www.w3.org/2000/svg}text")]


def test_gap_chart_is_well_formed_and_shows_the_gap(mock_doc):
    docs = [d for _, d in baseline_entries()] + [mock_doc]
    svg = svg_gap_chart(docs)
    root = parse(svg)
    assert root.tag.endswith("svg") and root.get("role") == "img"
    labels = " ".join(texts(root))
    assert "pass@1" in labels and "pass^" in labels and "gap" in labels and "[MOCK] example-model" in labels
    assert "prefers-color-scheme: dark" in svg and "nan" not in svg.lower()
    rows = gap_rows(docs)
    assert any(r["label"] == "scripted-oracle" for r in rows) and any(
        r["env"].endswith("fault=mixed:0.3") for r in rows
    )
    assert not any("naive" in r["env"] or "inject" in r["env"] for r in rows)


def test_gap_chart_with_no_rows_still_renders():
    only_noop = [d for _, d in baseline_entries() if d["agent"]["name"] == "no-op"]
    assert "no rows to plot" in svg_gap_chart(only_noop)


def test_audit_chart_marks_flags_with_text_not_just_colour():
    svg = svg_audit_chart([d for _, d in baseline_entries()])
    root = parse(svg)
    labels = texts(root)
    assert any("threshold 5%" in t for t in labels)
    assert sum("FLAG" in t for t in labels) >= 7, "naive-grader rows carry a FLAG label"
    assert any("Demonstration" in t for t in labels)
    assert 'class="bc"' in svg and 'class="b1"' in svg
    assert "No-op" not in svg  # labels use the agent names exactly as recorded


def test_audit_chart_without_demo_rows_has_no_flags():
    docs = []
    for _, d in baseline_entries():
        d = copy.deepcopy(d)
        d["environments"] = {k: v for k, v in d["environments"].items() if "+" not in k}
        docs.append(d)
    svg = svg_audit_chart(docs)
    assert "FLAG" not in svg.replace("FLAG: above threshold", "") and "Demonstration" not in svg


def test_write_report_creates_markdown_and_two_svgs(tmp_path):
    written = write_report(baseline_entries(), tmp_path / "r")
    assert [p.name for p in written] == ["report.md", "pass1_vs_passk.svg", "audit.svg"]
    for p in written[1:]:
        parse(p.read_text())


def test_cli_report_end_to_end(tmp_path, capsys, mock_doc):
    write_results(tmp_path / "in" / "mock.json", mock_doc)
    write_results(tmp_path / "in" / "b.json", load_results(RESULTS / "baseline-noop.json"))
    assert cli.main(["report", str(tmp_path / "in"), "--out-dir", str(tmp_path / "out"), "--print"]) == 0
    out = capsys.readouterr().out
    assert "wrote" in out and "# trialgauntlet report" in out and "MOCK" in out
    assert (tmp_path / "out" / "audit.svg").exists()


# ----------------------------------------------------------------------------------- leaderboard
def test_leaderboard_excludes_mock_unless_asked(mock_doc):
    entries = baseline_entries() + entries_for(mock_doc)
    lb = build_leaderboard(entries)
    assert lb["schema"] == LEADERBOARD_SCHEMA and not any(e["mock"] for e in lb["entries"])
    lb2 = build_leaderboard(entries, include_mock=True)
    mock = [e for e in lb2["entries"] if e["mock"]]
    assert mock and all(e["label"] == "MOCK" and e["agent"] == "example-model" for e in mock)
    assert lb2["entries"][0]["type"] == "llm", "model entries sort ahead of baselines"


def test_leaderboard_entries_have_exactly_the_documented_fields():
    lb = build_leaderboard(baseline_entries())
    assert lb["entries"] and all(set(e) == set(ENTRY_FIELDS) for e in lb["entries"])
    schema = json.loads((ROOT / "docs" / "leaderboard.schema.json").read_text())
    assert set(schema["properties"]["entries"]["items"]["properties"]) == set(ENTRY_FIELDS)
    assert set(schema["properties"]["entries"]["items"]["required"]) == set(ENTRY_FIELDS)
    assert schema["properties"]["schema"]["const"] == LEADERBOARD_SCHEMA


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda d: d.update(schema="x"), "not a"),
        (lambda d: d.update(entries="no"), "must be a list"),
        (lambda d: d["entries"].append(5), "must be an object"),
        (lambda d: d["entries"][0].pop("pass^k"), "missing"),
        (lambda d: d["entries"][0].update({"pass@1": 1.5}), "must be in"),
        (lambda d: d["entries"][0].update(label="FAKE"), "invalid label"),
        (lambda d: d["entries"][0].update(mock=True), "disagrees"),
        (lambda d: d["entries"][0].update(k=99, n=2), "k exceeds n"),
    ],
)
def test_leaderboard_validation(mutate, fragment):
    doc = build_leaderboard(baseline_entries())
    mutate(doc)
    with pytest.raises(LeaderboardError, match=fragment):
        validate_leaderboard(doc)


def test_cli_leaderboard_build_and_validate(tmp_path, capsys):
    out = tmp_path / "lb.json"
    assert cli.main(["leaderboard", str(RESULTS), "--out", str(out)]) == 0
    assert cli.main(["leaderboard", "--validate", str(out)]) == 0
    assert "valid" in capsys.readouterr().out
    assert load_leaderboard(out)["entries"]
    out.write_text("{}")
    assert cli.main(["leaderboard", "--validate", str(out)]) == 2
    assert cli.main(["leaderboard", str(tmp_path / "empty"), "--out", str(out)]) == 2
    assert cli.main(["leaderboard", "--validate", str(tmp_path / "nope.json")]) == 2
