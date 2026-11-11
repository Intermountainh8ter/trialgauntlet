from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "heterogeneity_gap.py"
spec = importlib.util.spec_from_file_location("heterogeneity_gap", SCRIPT)
hg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hg)


def test_markov_marginal_and_autocorr():
    rows = hg.gen_markov(400, 16, 0.7, 0.5, random.Random(1))
    assert abs(hg.pooled_p1(rows) - 0.7) < 0.05
    assert hg.lag1_autocorr(rows) > 0.2


def test_iid_homogeneous_has_no_positive_autocorr():
    rows = [[1 if random.Random(i).random() < 0.5 else 0 for _ in range(16)] for i in range(5)]
    rows = hg.gen_markov(300, 16, 0.5, 0.0, random.Random(2))
    assert abs(hg.lag1_autocorr(rows)) < 0.15


def test_run_deterministic_and_cli(tmp_path):
    assert hg.run(3, 8, 4, 20) == hg.run(3, 8, 4, 20)
    p = tmp_path / "r.json"
    assert hg.main(["--seed", "7", "--n", "8", "--k-max", "4", "--boot", "20", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"] and "k_4" in d["heterogeneity_gap"]
