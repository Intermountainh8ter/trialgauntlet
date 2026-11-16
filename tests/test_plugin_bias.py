from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "plugin_bias.py"
spec = importlib.util.spec_from_file_location("plugin_bias", SCRIPT)
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


def test_task_count():
    assert len(pb.task_ps()) == 138


def test_bias_deterministic_and_positive_at_small_n():
    ps = pb.task_ps()
    a = pb.bias_for_n(ps, 4, 4, 20, 3)
    assert a == pb.bias_for_n(ps, 4, 4, 20, 3)
    assert a["plugin_bias"] > 0


def test_main_writes_metric(tmp_path):
    out = tmp_path / "r.json"
    assert pb.main(["--seed", "1", "--k", "2", "--reps", "5", "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert "n8_k2" in doc["plugin_bias"]
    assert doc["provenance"]["started_at"]
