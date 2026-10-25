from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "ci_width.py"
spec = importlib.util.spec_from_file_location("ci_width", SCRIPT)
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)


def test_width_nonnegative_and_deterministic():
    out = cw.pk.simulate_outcomes(2, 8)
    a = cw.ci_width(out, 4, 2, 50)
    assert a == cw.ci_width(out, 4, 2, 50)
    assert a["width"] >= 0 and a["ci95"][0] <= a["ci95"][1]


def test_cli_writes_metric_and_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert cw.main(["--seed", "7", "--k", "4", "--n-list", "8,64", "--boot", "20", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"]
    assert "ratio_n8_over_n64_k4" in d["ci_width"]
