from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from trialgauntlet.agents.baselines import EscalateGuessAgent

SCRIPT = Path(__file__).parent.parent / "scripts" / "escalate_guess.py"
spec = importlib.util.spec_from_file_location("escalate_guess", SCRIPT)
eg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eg)


def test_cli_writes_metric_and_provenance(tmp_path):
    p = tmp_path / "r.json"
    assert eg.main(["--seed", "7", "--n", "8", "--k-max", "4", "--n-boot", "20", "--out", str(p)]) == 0
    d = json.loads(p.read_text())
    assert "started_at" in d["provenance"]
    c = d["escalate_guess"]["category_only"]
    assert c["pass_at_k"]["4"] >= c["pass_at_k"]["1"]
    assert c["pass_hat_k"]["4"] <= c["pass_hat_k"]["1"]
    f = d["escalate_guess"]["full"]
    assert f["pass_at_k"]["4"] <= c["pass_at_k"]["4"]


def test_deterministic(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for p in (a, b):
        eg.main(["--seed", "3", "--n", "4", "--k-max", "2", "--n-boot", "10", "--out", str(p)])
    da, db = json.loads(a.read_text()), json.loads(b.read_text())
    assert da["escalate_guess"] == db["escalate_guess"]


def test_agent_escalates_once():
    assert EscalateGuessAgent.name == "escalate-guess"
