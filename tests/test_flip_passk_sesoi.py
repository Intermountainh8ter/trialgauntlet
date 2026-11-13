from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "flip_passk_sesoi.py"
spec = importlib.util.spec_from_file_location("flip_passk_sesoi", SCRIPT)
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)


def test_zero_flip_matches_baseline():
    a = fp.curve(fp.simulate(3, 8, 0.0), 4)
    b = fp.curve(fp.simulate(3, 8, 0.0), 4)
    assert a == b


def test_flip_lowers_high_k_passk():
    base = fp.curve(fp.simulate(3, 8, 0.0), 8)
    cur = fp.curve(fp.simulate(3, 8, 0.3), 8)
    assert cur[7] < base[7]


def test_first_divergent():
    assert fp.first_divergent([1, 1, 1], [1, 0.9, 0.5], 0.05, 3) == 2
    assert fp.first_divergent([1, 1], [1, 1], 0.05, 2) is None


def test_cli_writes_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert fp.main(["--seed", "11", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"] and "k_first_divergent" in d["flip_passk"]
