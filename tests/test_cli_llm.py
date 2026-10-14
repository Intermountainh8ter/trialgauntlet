from __future__ import annotations

import json

import pytest

from trialgauntlet import cli
from trialgauntlet.mockserver import MockServer
from trialgauntlet.results import load_results


@pytest.fixture(scope="module")
def oracle_server():
    with MockServer("oracle") as server:
        yield server


def run_llm(url, *extra, env="config", n="2", k="2", limit="4"):
    return cli.main(
        [
            "run",
            "--agent",
            "llm",
            "--base-url",
            url,
            "--env",
            env,
            "--n",
            n,
            "--k",
            k,
            "--limit",
            limit,
            "--n-boot",
            "20",
            "--quiet",
            *extra,
        ]
    )


def test_llm_run_against_the_mock_is_labelled_mock_and_records_provenance(oracle_server, tmp_path, capsys):
    out = tmp_path / "r.json"
    assert run_llm(oracle_server.url, "--model", "example-model", "--temperature", "0.5", "--out", str(out)) == 0
    captured = capsys.readouterr()
    assert "MOCK run" in captured.err and "(label MOCK)" in captured.out
    doc = load_results(out)
    assert doc["label"] == "MOCK" and doc["agent"]["type"] == "llm" and doc["agent"]["model"] == "example-model"
    assert doc["agent"]["temperature"] == 0.5 and doc["run"]["created"].endswith("+00:00")
    s = doc["environments"]["config"]
    assert s["metrics"]["pass@1"]["value"] == 1.0
    assert s["usage"]["mean_prompt_tokens"] > 0 and s["usage"]["mean_agent_latency_s"] is not None


def test_model_name_is_discovered_from_the_server(oracle_server, tmp_path, capsys):
    out = tmp_path / "r.json"
    assert run_llm(oracle_server.url, "--out", str(out)) == 0
    assert "using model 'mock-model'" in capsys.readouterr().err
    assert load_results(out)["agent"]["name"] == "mock-model"


def test_cannot_claim_real_for_the_mock(oracle_server, capsys):
    assert run_llm(oracle_server.url, "--model", "m", "--label", "REAL", "--out", "unused.json") == 2
    assert "built-in mock" in capsys.readouterr().err


def test_price_flags_and_budgets_are_applied(oracle_server, tmp_path):
    out = tmp_path / "r.json"
    assert (
        run_llm(oracle_server.url, "--model", "m", "--price-in", "1000", "--price-out", "2000", "--out", str(out)) == 0
    )
    assert load_results(out)["environments"]["config"]["usage"]["cost_usd"] > 0
    out2 = tmp_path / "r2.json"
    assert run_llm(oracle_server.url, "--model", "m", "--max-trial-tokens", "10", "--out", str(out2)) == 0
    s = load_results(out2)["environments"]["config"]
    assert s["terminated"] == {"budget:tokens": 8} and s["metrics"]["pass@1"]["value"] == 0.0


def test_flaky_mock_shows_the_gap(tmp_path, capsys):
    with MockServer("flaky", flaky=0.1) as server:
        out = tmp_path / "f.json"
        argv = ["run", "--agent", "llm", "--base-url", server.url, "--model", "m", "--env", "config"]
        argv += ["--n", "8", "--k", "4", "--limit", "20", "--n-boot", "50", "--temperature", "0.7", "--quiet"]
        code = cli.main([*argv, "--out", str(out)])
    assert code == 0
    m = load_results(out)["environments"]["config"]["metrics"]
    assert m["pass^k"]["value"] < m["pass@1"]["value"] < 1.0
    assert "pass@1     " in capsys.readouterr().out


def test_progress_lines_go_to_stderr(oracle_server, capsys):
    cli.main(
        [
            "run",
            "--agent",
            "llm",
            "--base-url",
            oracle_server.url,
            "--model",
            "m",
            "--env",
            "config",
            "--n",
            "1",
            "--k",
            "1",
            "--limit",
            "2",
            "--n-boot",
            "10",
        ]
    )
    err = capsys.readouterr().err
    assert "[config] task 0 (T1 feature_flag) done" in err


def test_resume_hint_on_connection_failure(tmp_path, capsys):
    code = run_llm(
        "http://127.0.0.1:9/v1", "--model", "m", "--retries", "0", "--timeout", "2", "--run-dir", str(tmp_path)
    )
    err = capsys.readouterr().err
    assert code == 2 and "connection refused" in err and "re-run the same command to resume" in err
    code = run_llm("http://127.0.0.1:9/v1", "--model", "m", "--retries", "0", "--timeout", "2")
    assert "Use --run-dir" in capsys.readouterr().err and code == 2


def test_interrupted_llm_run_resumes_from_the_trajectories(tmp_path, capsys):
    with MockServer("oracle") as server:
        args = ["--model", "m", "--run-dir", str(tmp_path), "--out", str(tmp_path / "r.json")]
        assert run_llm(server.url, *args) == 0
        first = len(server.requests)
        assert run_llm(server.url, *args) == 0
        assert len(server.requests) == first
    capsys.readouterr()


@pytest.mark.parametrize(
    "extra,message",
    [
        ([], "needs --base-url"),
        (["--base-url", "http://127.0.0.1:9/v1", "--api-key-env", "TG_SURELY_UNSET_KEY", "--model", "m"], "is not set"),
        (["--base-url", "http://127.0.0.1:9/v1", "--model", "m", "--extra-body", "{nope"], "not valid JSON"),
        (["--base-url", "http://127.0.0.1:9/v1", "--model", "m", "--extra-body", "[1]"], "must be a JSON object"),
        (["--base-url", "http://127.0.0.1:9/v1"], "model list could not be read"),
    ],
)
def test_llm_argument_errors(extra, message, capsys, monkeypatch):
    monkeypatch.delenv("TG_SURELY_UNSET_KEY", raising=False)
    assert cli.main(["run", "--agent", "llm", "--env", "config", "--n", "1", "--k", "1", *extra]) == 2
    assert message in capsys.readouterr().err


def test_api_key_is_read_from_the_named_environment_variable(monkeypatch, capsys):
    monkeypatch.setenv("TG_TEST_KEY", "abc123")
    with MockServer("oracle") as server:
        assert run_llm(server.url, "--model", "m", "--api-key-env", "TG_TEST_KEY") == 0
        assert all(h.get("Authorization") == "Bearer abc123" for h in server.headers)
    capsys.readouterr()


def test_extra_body_reaches_the_server(capsys):
    with MockServer("oracle") as server:
        assert (
            run_llm(server.url, "--model", "m", "--extra-body", '{"chat_template_kwargs": {"enable_thinking": false}}')
            == 0
        )
        assert server.requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    capsys.readouterr()


# ----------------------------------------------------------------------------------- doctor
def test_doctor_passes_against_a_conforming_server(oracle_server, capsys):
    assert cli.main(["doctor", "--base-url", oracle_server.url]) == 0
    out = capsys.readouterr().out
    assert "[PASS] server reachable" in out and "[PASS] structured tool call" in out and "MOCK" in out


def test_doctor_diagnoses_tool_calls_returned_as_text(capsys):
    with MockServer("text") as server:
        assert cli.main(["doctor", "--base-url", server.url, "--model", "m"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out and "--jinja" in out and "--parse-text-tools" in out


def test_doctor_diagnoses_prose_replies_and_malformed_calls(capsys):
    with MockServer("noop") as server:
        assert cli.main(["doctor", "--base-url", server.url]) == 1
    assert "answered in prose" in capsys.readouterr().out
    with MockServer("malformed") as server:
        assert cli.main(["doctor", "--base-url", server.url]) == 1
    assert "malformed" in capsys.readouterr().out


def test_doctor_connection_refused_gives_a_fix(capsys):
    assert cli.main(["doctor", "--base-url", "http://127.0.0.1:9", "--timeout", "2"]) == 1
    out = capsys.readouterr().out
    assert "connection refused" in out and "llama-server --jinja" in out


def test_doctor_reports_http_errors_from_the_chat_endpoint(capsys):
    with MockServer("http500", fail_first=99) as server:
        assert cli.main(["doctor", "--base-url", server.url]) == 1
    assert "chat request failed" in capsys.readouterr().out


def test_end_to_end_mock_pipeline_run_report_leaderboard(tmp_path, capsys):
    with MockServer("flaky", flaky=0.05) as server:
        out = tmp_path / "results" / "mock-run.json"
        assert (
            run_llm(server.url, "--model", "example-model", "--out", str(out), env="all", n="4", k="2", limit="6") == 0
        )
    assert cli.main(["report", str(tmp_path / "results"), "--out-dir", str(tmp_path / "rep")]) == 0
    md = (tmp_path / "rep" / "report.md").read_text()
    assert "LLM results: NOT YET RUN" in md and "MOCK" in md
    assert cli.main(["leaderboard", str(tmp_path / "results"), "--out", str(tmp_path / "lb.json")]) == 0
    assert json.loads((tmp_path / "lb.json").read_text())["entries"] == []
    assert (
        cli.main(["leaderboard", str(tmp_path / "results"), "--out", str(tmp_path / "lb2.json"), "--include-mock"]) == 0
    )
    assert len(json.loads((tmp_path / "lb2.json").read_text())["entries"]) == 3
    capsys.readouterr()
