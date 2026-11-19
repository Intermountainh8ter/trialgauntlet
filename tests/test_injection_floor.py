from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("injection_floor", SCRIPTS / "injection_floor.py")
inf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inf)


def test_measure_covers_every_cell():
    cells = inf.measure("no_op", 1, 7)
    assert set(cells) == set(inf.ENVS)
    assert all(set(v) == set(inf.VARIANTS) for v in cells.values())


def test_noop_never_attacked():
    cells = inf.measure("no_op", 1, 7)
    assert all(c["attack_success_rate"] == 0.0 for v in cells.values() for c in v.values())


def test_cli_writes_metric_and_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert inf.main(["--seed", "7", "--n", "1", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"]
    assert d["floor"]["by_stub"]["always_refuse"]["attack_success_rate"] == 0.0
