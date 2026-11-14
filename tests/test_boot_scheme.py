from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "boot_scheme.py"
spec = importlib.util.spec_from_file_location("boot_scheme", SCRIPT)
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


@pytest.mark.parametrize("scheme", ["task", "rollout", "hierarchical"])
def test_scheme_deterministic_and_ordered(scheme):
    out = bs.pk.simulate_outcomes(2, 8)
    a = bs.scheme_width(out, 4, 2, 30, scheme)
    assert a == bs.scheme_width(out, 4, 2, 30, scheme)
    assert a["width"] >= 0 and a["ci95"][0] <= a["ci95"][1]


def test_unknown_scheme_rejected():
    with pytest.raises(ValueError):
        bs.scheme_width(bs.pk.simulate_outcomes(2, 8), 4, 2, 5, "nope")


def test_cli_writes_metric_and_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert bs.main(["--seed", "7", "--n", "8", "--k", "4", "--boot", "20", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"]
    assert "task_over_rollout_k4" in d["interval_width_ratio"]
