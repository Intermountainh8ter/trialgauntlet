from __future__ import annotations

import copy
import json

import pytest
from helpers import ToyEnv, ToyOracle

from trialgauntlet.results import (
    RESULTS_SCHEMA,
    ResultsError,
    build_results,
    label_is_llm,
    load_results,
    validate_results,
    write_results,
)
from trialgauntlet.runner import run_suite
from trialgauntlet.summary import summarize_env


@pytest.fixture
def doc():
    results = run_suite(ToyEnv, ToyOracle, range(10), 3, env_spec="toy")
    summary = summarize_env(results, 2, n_boot=20, include_timing=False)
    return build_results(
        agent={"name": "scripted-oracle", "id": "x", "type": "baseline", "config": {}},
        label="BASELINE",
        summaries={"toy": summary},
        run={"n": 3, "k": 2, "seed": 0},
    )


def test_build_sets_schema_and_version(doc):
    assert doc["schema"] == RESULTS_SCHEMA and doc["label"] == "BASELINE" and doc["harness_version"]
    assert doc["environments"]["toy"]["usage"]["mean_wall_s"] is None


def test_write_then_load_roundtrip_and_stable_bytes(doc, tmp_path):
    write_results(tmp_path / "x" / "r.json", doc)
    write_results(tmp_path / "y.json", doc)
    assert load_results(tmp_path / "x" / "r.json") == doc
    assert (tmp_path / "x" / "r.json").read_bytes() == (tmp_path / "y.json").read_bytes()


def test_label_must_be_known():
    with pytest.raises(ResultsError, match="label"):
        build_results(agent={}, label="REAL-ISH", summaries={}, run={})


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda d: d.update(schema="other/9"), "unsupported schema"),
        (lambda d: d.pop("run"), "missing run"),
        (lambda d: d["run"].update(n="8"), "run.n"),
        (lambda d: d["agent"].update(type="robot"), "agent needs"),
        (lambda d: d.update(environments={}), "non-empty"),
        (lambda d: d["environments"]["toy"].pop("per_task"), "missing 'per_task'"),
        (lambda d: d["environments"]["toy"]["metrics"]["pass@1"].update(value=1.5), r"in \[0,1\]"),
        (lambda d: d["environments"]["toy"]["metrics"]["pass^k"].update(ci=[0.9, 0.1]), "ci must be"),
        (lambda d: d["environments"]["toy"].update(tasks=3), "does not match"),
        (lambda d: d["environments"]["toy"]["per_task"][0].update(c=99), "out of range"),
    ],
)
def test_validation_rejects_malformed_documents(doc, mutate, fragment):
    bad = copy.deepcopy(doc)
    mutate(bad)
    with pytest.raises(ResultsError, match=fragment):
        validate_results(bad)


def test_llm_results_need_a_model(doc):
    bad = copy.deepcopy(doc)
    bad["agent"]["type"] = "llm"
    assert label_is_llm(bad)
    with pytest.raises(ResultsError, match="model"):
        validate_results(bad)
    bad["agent"]["model"] = "example-model"
    validate_results(bad)


def test_non_object_documents_are_rejected():
    with pytest.raises(ResultsError):
        validate_results([1, 2])


def test_load_reports_unreadable_and_invalid_files(tmp_path):
    with pytest.raises(ResultsError, match="cannot read"):
        load_results(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(ResultsError, match="cannot read"):
        load_results(tmp_path / "bad.json")
    (tmp_path / "wrong.json").write_text(json.dumps({"schema": "nope"}))
    with pytest.raises(ResultsError, match="wrong.json"):
        load_results(tmp_path / "wrong.json")
