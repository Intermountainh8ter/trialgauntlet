"""Result files: one JSON document per (agent, run). The format is documented in docs/METHODOLOGY.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trialgauntlet import __version__

RESULTS_SCHEMA = "trialgauntlet.results/1"
LABELS = ("BASELINE", "REAL", "MOCK")
AGENT_TYPES = ("baseline", "llm")
METRIC_NAMES = ("pass@1", "pass@k", "pass^k", "gap")


class ResultsError(ValueError):
    """A results document is malformed or cannot be used."""


def build_results(
    *,
    agent: dict[str, Any],
    label: str,
    summaries: dict[str, dict[str, Any]],
    run: dict[str, Any],
) -> dict[str, Any]:
    if label not in LABELS:
        raise ResultsError(f"label must be one of {LABELS}, got {label!r}")
    doc = {
        "schema": RESULTS_SCHEMA,
        "label": label,
        "harness_version": __version__,
        "agent": agent,
        "run": run,
        "environments": summaries,
    }
    validate_results(doc)
    return doc


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ResultsError(msg)


def _unit(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and -1e-9 <= x <= 1 + 1e-9


def validate_results(doc: Any) -> None:
    """Structural validation. Raises :class:`ResultsError` with the first problem found."""
    _need(isinstance(doc, dict), "results document must be a JSON object")
    _need(doc.get("schema") == RESULTS_SCHEMA, f"unsupported schema {doc.get('schema')!r}, expected {RESULTS_SCHEMA}")
    _need(doc.get("label") in LABELS, f"label must be one of {LABELS}")
    agent = doc.get("agent")
    _need(
        isinstance(agent, dict) and agent.get("name") and agent.get("type") in AGENT_TYPES, "agent needs name and type"
    )
    run = doc.get("run")
    _need(isinstance(run, dict), "missing run block")
    for key in ("n", "k", "seed"):
        _need(isinstance(run.get(key), int), f"run.{key} must be an integer")
    envs = doc.get("environments")
    _need(isinstance(envs, dict) and envs, "environments must be a non-empty object")
    for spec, summary in envs.items():
        where = f"environments.{spec}"
        _need(isinstance(summary, dict), f"{where} must be an object")
        for key in ("tasks", "trials", "k", "metrics", "per_task", "usage", "reliability"):
            _need(key in summary, f"{where} is missing '{key}'")
        metrics = summary["metrics"]
        for name in ("pass@1", "pass@k", "pass^k"):
            _need(
                name in metrics and _unit(metrics[name].get("value")), f"{where}.metrics.{name}.value must be in [0,1]"
            )
            ci = metrics[name].get("ci")
            _need(ci is None or (len(ci) == 2 and ci[0] <= ci[1]), f"{where}.metrics.{name}.ci must be [lo, hi]")
        _need(summary["tasks"] == len(summary["per_task"]), f"{where}.tasks does not match per_task")
        for row in summary["per_task"]:
            _need(0 <= row["c"] <= row["n"], f"{where}: per_task success count out of range")
    if label_is_llm(doc):
        _need(agent.get("model"), "llm results need agent.model")


def label_is_llm(doc: dict[str, Any]) -> bool:
    return doc.get("agent", {}).get("type") == "llm"


def write_results(path: Path, doc: dict[str, Any]) -> None:
    validate_results(doc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_results(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ResultsError(f"cannot read results file {path}: {err}") from err
    try:
        validate_results(doc)
    except ResultsError as err:
        raise ResultsError(f"{path}: {err}") from err
    return doc
