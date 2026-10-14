"""Leaderboard JSON: one flat list of (agent, environment) entries built from result files.

Schema ``trialgauntlet.leaderboard/1`` (also described in ``docs/leaderboard.schema.json``). MOCK runs
are excluded unless explicitly requested, and always carry ``"mock": true`` when included.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from trialgauntlet.report import Doc, classify

LEADERBOARD_SCHEMA = "trialgauntlet.leaderboard/1"
ENTRY_FIELDS = (
    "agent", "type", "label", "mock", "environment", "spec", "tasks", "n", "k", "pass@1", "pass@1_ci", "pass@k",
    "pass^k", "pass^k_ci", "gap", "outcome_only", "violation_rate", "mean_tool_misuse", "mean_steps",
    "mean_tokens", "cost_usd", "source",
)  # fmt: skip


class LeaderboardError(ValueError):
    pass


def build_leaderboard(entries: Sequence[tuple[Path, Doc]], include_mock: bool = False) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path, doc in entries:
        kind = classify(doc)
        if kind == "mock" and not include_mock:
            continue
        for spec, s in doc["environments"].items():
            m, u, r = s["metrics"], s["usage"], s["reliability"]
            n = s["n"] if isinstance(s["n"], int) else min(s["n"])
            rows.append(
                {
                    "agent": doc["agent"]["name"],
                    "type": doc["agent"]["type"],
                    "label": doc["label"],
                    "mock": kind == "mock",
                    "environment": spec.split("+", 1)[0],
                    "spec": spec,
                    "tasks": s["tasks"],
                    "n": n,
                    "k": s["k"],
                    "pass@1": m["pass@1"]["value"],
                    "pass@1_ci": m["pass@1"].get("ci"),
                    "pass@k": m["pass@k"]["value"],
                    "pass^k": m["pass^k"]["value"],
                    "pass^k_ci": m["pass^k"].get("ci"),
                    "gap": m["gap"]["value"],
                    "outcome_only": m["outcome_only"]["value"],
                    "violation_rate": r["violation_rate"],
                    "mean_tool_misuse": r["mean_tool_misuse"],
                    "mean_steps": u["mean_steps"],
                    "mean_tokens": round(u["mean_prompt_tokens"] + u["mean_completion_tokens"], 2),
                    "cost_usd": u["cost_usd"],
                    "source": path.name,
                }
            )
    rows.sort(key=lambda e: (e["type"] != "llm", e["mock"], e["spec"], -e["pass^k"], e["agent"]))
    doc_out = {"schema": LEADERBOARD_SCHEMA, "entries": rows}
    validate_leaderboard(doc_out)
    return doc_out


def validate_leaderboard(doc: Any) -> None:
    if not isinstance(doc, dict) or doc.get("schema") != LEADERBOARD_SCHEMA:
        raise LeaderboardError(f"not a {LEADERBOARD_SCHEMA} document")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise LeaderboardError("entries must be a list")
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise LeaderboardError(f"entries[{i}] must be an object")
        missing = [f for f in ENTRY_FIELDS if f not in e]
        if missing:
            raise LeaderboardError(f"entries[{i}] is missing {missing}")
        for f in ("pass@1", "pass@k", "pass^k", "outcome_only", "violation_rate"):
            if not isinstance(e[f], (int, float)) or not -1e-9 <= e[f] <= 1 + 1e-9:
                raise LeaderboardError(f"entries[{i}].{f} must be in [0, 1]")
        if not isinstance(e["mock"], bool) or e["label"] not in ("BASELINE", "REAL", "MOCK"):
            raise LeaderboardError(f"entries[{i}] has an invalid label or mock flag")
        if e["mock"] != (e["label"] == "MOCK"):
            raise LeaderboardError(f"entries[{i}]: mock flag disagrees with label")
        if e["k"] > e["n"]:
            raise LeaderboardError(f"entries[{i}]: k exceeds n")


def load_leaderboard(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise LeaderboardError(f"cannot read {path}: {err}") from err
    validate_leaderboard(doc)
    return doc


def write_leaderboard(path: Path, doc: dict[str, Any]) -> None:
    validate_leaderboard(doc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
