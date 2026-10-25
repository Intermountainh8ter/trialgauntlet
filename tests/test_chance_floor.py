from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "chance_floor.py"
spec = importlib.util.spec_from_file_location("chance_floor", SCRIPT)
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)


def test_identical_arms_have_zero_gap():
    out = cf.pk.simulate_outcomes(2, 8)
    c = cf.gap_curve(out, out, 4, 2, 20)
    assert all(v["gap_over_chance"] == 0 for v in c.values())


def test_cli_writes_metric_and_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert cf.main(["--seed", "7", "--n", "8", "--k-max", "4", "--n-boot", "20", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"]
    assert "max_gap_over_chance_k4" in d["chance_audit"]
