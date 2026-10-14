"""Documentation must not drift from the code it describes."""

from __future__ import annotations

from pathlib import Path

import pytest

from trialgauntlet.envs import make_env

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["fleet", "ledger", "config"])
def test_environments_doc_lists_every_kind_with_tier_and_expectation(name):
    text = (ROOT / "docs" / "ENVIRONMENTS.md").read_text()
    env = make_env(name)
    section = text.split(f"## {name} ")[1].split("\n## ")[0]
    kinds = {s.kind: s for s in env.task_specs()}
    for kind, spec in kinds.items():
        row = next((line for line in section.splitlines() if line.startswith(f"| {kind} |")), None)
        assert row is not None, f"{kind} missing from docs/ENVIRONMENTS.md"
        assert f"| {spec.tier} |" in row
        assert ("escalate" in row) == (spec.expect == "escalate")
    assert f"{len(env.task_specs())} tasks" in section.splitlines()[0]
