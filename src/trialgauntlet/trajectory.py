"""Trajectory JSONL: one file per trial, written incrementally, replayable.

Layout (one JSON object per line)::

    {"type": "header", ...}      run metadata and the first observation
    {"type": "step", ...}        one per agent turn: the action and the observation it produced
    {"type": "end", ...}         termination reason, grade, state digest, full trial result

A file is written as ``<name>.jsonl.partial`` and atomically renamed when the ``end`` record is
written, so a file ending in ``.jsonl`` is always complete and an interrupted run leaves only a
partial file that the runner overwrites.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from trialgauntlet.models import SCHEMA_VERSION, Action, TrialResult


class TrajectoryError(Exception):
    pass


class TrajectoryWriter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.partial = self.path.with_name(self.path.name + ".partial")
        self._fh: TextIO | None = None

    def write(self, record: dict[str, Any]) -> None:
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.partial.open("w", encoding="utf-8")
        self._fh.write(json.dumps(record, sort_keys=True) + "\n")
        self._fh.flush()

    def close(self) -> None:
        """Commit: close and atomically rename to the final name."""
        if self._fh is None:
            raise TrajectoryError("nothing was written")
        self._fh.close()
        self._fh = None
        os.replace(self.partial, self.path)

    def abort(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class MemoryRecorder(TrajectoryWriter):
    """Collects records in memory instead of writing a file (used by replay and tests)."""

    def __init__(self) -> None:
        super().__init__(Path("memory.jsonl"))
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)

    def close(self) -> None:
        return None


@dataclass
class Trajectory:
    header: dict[str, Any]
    steps: list[dict[str, Any]] = field(default_factory=list)
    end: dict[str, Any] = field(default_factory=dict)

    def actions(self) -> list[Action]:
        return [Action.from_dict(s["action"]) for s in self.steps]

    def result(self) -> TrialResult:
        return TrialResult.from_dict(self.end["result"])


def read_trajectory(path: Path) -> Trajectory:
    header: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = []
    end: dict[str, Any] | None = None
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as err:
        raise TrajectoryError(f"cannot read {path}: {err}") from err
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as err:
            raise TrajectoryError(f"{path}:{number}: invalid JSON ({err.msg})") from err
        kind = rec.get("type")
        if kind == "header":
            header = rec
        elif kind == "step":
            steps.append(rec)
        elif kind == "end":
            end = rec
        else:
            raise TrajectoryError(f"{path}:{number}: unknown record type {kind!r}")
    if header is None:
        raise TrajectoryError(f"{path}: missing header record")
    if end is None:
        raise TrajectoryError(f"{path}: incomplete trajectory (no end record)")
    if header.get("schema") != SCHEMA_VERSION:
        raise TrajectoryError(f"{path}: unsupported schema {header.get('schema')!r}")
    return Trajectory(header=header, steps=steps, end=end)


def is_complete(path: Path) -> bool:
    try:
        read_trajectory(path)
    except TrajectoryError:
        return False
    return True


def trajectory_path(run_dir: Path, env_spec: str, task_seed: int, trial: int) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in env_spec)
    return Path(run_dir) / "trajectories" / safe / f"{task_seed:04d}-{trial:02d}.jsonl"
