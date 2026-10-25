from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "passk_decay.py"
spec = importlib.util.spec_from_file_location("passk_decay", SCRIPT)
pk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pk)


def test_simulation_is_seeded():
    a = pk.simulate_outcomes(3, 8)
    b = pk.simulate_outcomes(3, 8)
    assert [o.c for o in a] == [o.c for o in b]
    assert len(a) == 138


def test_perfect_tiers_have_zero_gap():
    out = pk.simulate_outcomes(1, 8, {"T1": 1.0, "T2": 1.0, "T3": 1.0})
    c = pk.curve(out, 4, 1, 20)
    assert all(v["gap_vs_independence"] == 0 for v in c.values())


def test_cli_writes_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert pk.main(["--seed", "7", "--n", "8", "--k-max", "4", "--n-boot", "20", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"] and "gap_vs_independence" in d["pass_hat_k"]["4"]


def test_report_collect_skips_analysis_files(tmp_path):
    import pytest

    from trialgauntlet.report import ReportError, collect

    (tmp_path / "x.json").write_text(json.dumps({"pass_hat_k": {}, "provenance": {}}))
    with pytest.raises(ReportError, match="no result files"):
        collect([tmp_path])
