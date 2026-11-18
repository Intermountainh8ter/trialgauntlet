from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("closed_form_floor", SCRIPTS / "closed_form_floor.py")
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)


def test_closed_form_values():
    assert cf.closed_form([0.5, 0.0], 2) == {"1": 0.25, "2": 0.125}


def test_probs_in_unit_interval():
    qs = cf.task_hit_probs()
    assert qs and all(0.0 <= q <= 1.0 for q in qs)


def test_cli_writes_metric_and_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert cf.main(["--seed", "7", "--n", "4", "--k-max", "2", "--n-boot", "10", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"]
    assert d["floor"]["max_abs_deviation_category_only"] >= 0.0
