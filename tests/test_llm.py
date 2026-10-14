"""The OpenAI-compatible adapter, exercised over real HTTP against the scripted mock server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from trialgauntlet.agents import llm as llm_module
from trialgauntlet.agents.llm import (
    LLMAgent,
    LLMConfig,
    LLMConnectionError,
    LLMError,
    LLMHTTPError,
    chat_url,
    http_json,
    looks_like_text_tool_call,
    models_url,
    parse_text_tool_call,
)
from trialgauntlet.envs import make_env
from trialgauntlet.mockserver import MODES, MockServer, infer_env, oracle_next_action
from trialgauntlet.models import ToolSpec
from trialgauntlet.runner import replay_trajectory, run_suite, run_trial
from trialgauntlet.schema import object_schema
from trialgauntlet.trajectory import TrajectoryWriter, trajectory_path


def agent_for(server, **kw):
    sleeps = []
    cfg = LLMConfig(base_url=server.url, model="example-model", **kw)
    return LLMAgent(cfg, sleep=sleeps.append), sleeps


@pytest.mark.parametrize(
    "base,chat,models",
    [
        ("http://h:8080", "http://h:8080/v1/chat/completions", "http://h:8080/v1/models"),
        ("http://h:8080/", "http://h:8080/v1/chat/completions", "http://h:8080/v1/models"),
        ("http://h:8080/v1", "http://h:8080/v1/chat/completions", "http://h:8080/v1/models"),
        ("http://h:8080/v1/", "http://h:8080/v1/chat/completions", "http://h:8080/v1/models"),
        ("http://h/v1/chat/completions", "http://h/v1/chat/completions", "http://h/v1/models"),
    ],
)
def test_url_normalisation(base, chat, models):
    assert chat_url(base) == chat and models_url(base) == models


@pytest.mark.parametrize("name", ["fleet", "ledger", "config"])
def test_correct_tool_calls_pass_every_environment_over_http(name):
    env = make_env(name)
    with MockServer("oracle") as server:
        agent, _ = agent_for(server, temperature=0.3)
        for seed in env.task_seeds()[::4]:
            r = run_trial(env, agent, seed)
            assert r.passed, (seed, r.reason)
            assert r.prompt_tokens > 0 and r.completion_tokens > 0 and r.agent_latency_s > 0
        assert agent.is_mock and agent.requests == len(server.requests)


def test_request_body_carries_tools_seed_temperature_and_a_consistent_history():
    env = make_env("ledger")
    with MockServer("oracle") as server:
        agent, _ = agent_for(server, temperature=0.7, top_p=0.9, max_tokens=321, extra_body={"top_k": 20})
        result = run_trial(env, agent, 14, trial=3, trial_seed=777)
        assert result.passed
        first, last = server.requests[0], server.requests[-1]
    assert first["model"] == "example-model" and first["seed"] == 777 and first["temperature"] == 0.7
    assert first["top_p"] == 0.9 and first["max_tokens"] == 321 and first["top_k"] == 20
    assert first["parallel_tool_calls"] is False and first["stream"] is False and first["tool_choice"] == "auto"
    assert {t["function"]["name"] for t in first["tools"]} == {t.name for t in env.tools()}
    assert first["messages"][0]["role"] == "system" and "refund" in first["messages"][0]["content"].lower()
    assert first["messages"][-1]["role"] == "user"
    msgs = last["messages"]
    calls = [m for m in msgs if m.get("tool_calls")]
    results = [m for m in msgs if m["role"] == "tool"]
    assert len(calls) == len(results) and calls
    for a, t in zip(calls, results):
        assert a["tool_calls"][0]["id"] == t["tool_call_id"]
        assert isinstance(a["tool_calls"][0]["function"]["arguments"], str)


def test_authorization_header_is_sent_only_with_a_key():
    with MockServer("oracle") as server:
        agent, _ = agent_for(server, api_key="secret-key")
        run_trial(make_env("config"), agent, 0)
        assert all(h.get("Authorization") == "Bearer secret-key" for h in server.headers)
        agent2, _ = agent_for(server)
        before = len(server.headers)
        run_trial(make_env("config"), agent2, 0)
        assert all("Authorization" not in h for h in server.headers[before:])


def test_tool_call_as_text_is_a_loud_format_error_by_default():
    with MockServer("text") as server:
        agent, _ = agent_for(server)
        r = run_trial(make_env("fleet"), agent, 0)
    assert r.terminated == "format_error" and r.format_errors == 3 and not r.passed


def test_parse_text_tools_opt_in_recovers_the_run():
    with MockServer("text") as server:
        agent, _ = agent_for(server, parse_text_tools=True)
        results = [run_trial(make_env("fleet"), agent, s) for s in range(0, 13, 3)]
    assert all(r.passed for r in results)


def test_malformed_arguments_are_a_format_error():
    with MockServer("malformed") as server:
        agent, _ = agent_for(server)
        r = run_trial(make_env("config"), agent, 0)
        history = server.requests[-1]["messages"]
    assert r.terminated == "format_error" and r.format_errors == 3
    assert not any(m.get("tool_calls") for m in history), "a malformed call must not enter the history as a call"
    assert any(m["role"] == "user" and "format_error" in m["content"] for m in history)


def test_prose_only_replies_are_nudged_once_then_the_trial_ends():
    with MockServer("noop") as server:
        agent, _ = agent_for(server)
        r = run_trial(make_env("fleet"), agent, 0)
        users = [m for m in server.requests[-1]["messages"] if m["role"] == "user"]
    assert r.terminated == "no_action" and len(server.requests) == 2 and "no_tool_call" in users[-1]["content"]


def test_refusing_model_fails_solvable_tasks_and_passes_none_here():
    with MockServer("refuse") as server:
        agent, _ = agent_for(server)
        rs = [run_trial(make_env("fleet"), agent, s) for s in (0, 1, 3)]
    assert [r.terminated for r in rs] == ["escalate"] * 3 and not any(r.passed for r in rs)


def test_only_the_first_of_several_parallel_tool_calls_is_executed_and_kept():
    with MockServer("parallel") as server:
        agent, _ = agent_for(server)
        r = run_trial(make_env("config"), agent, 0)
        assistant = [m for m in server.requests[-1]["messages"] if m.get("tool_calls")]
    assert r.passed and all(len(m["tool_calls"]) == 1 for m in assistant)


def test_transient_http_errors_are_retried_with_exponential_backoff():
    with MockServer("http500", fail_first=2) as server:
        agent, sleeps = agent_for(server, retries=3, backoff=0.5)
        r = run_trial(make_env("config"), agent, 0)
    assert r.passed and sleeps == [0.5, 1.0] and agent.retries_used == 2


def test_retries_are_bounded_and_the_last_error_is_raised():
    with MockServer("http500", fail_first=50) as server:
        agent, sleeps = agent_for(server, retries=2, backoff=0.1)
        with pytest.raises(LLMHTTPError) as exc:
            run_trial(make_env("config"), agent, 0)
    assert exc.value.status == 500 and "overloaded" in exc.value.body and sleeps == [0.1, 0.2]


def test_connection_refused_is_reported_with_a_fix():
    cfg = LLMConfig(base_url="http://127.0.0.1:9/v1", model="m", retries=1, timeout=2)
    sleeps = []
    agent = LLMAgent(cfg, sleep=sleeps.append)
    with pytest.raises(LLMConnectionError) as exc:
        run_trial(make_env("config"), agent, 0)
    text = str(exc.value)
    assert "127.0.0.1:9" in text and "connection refused" in text and "--jinja" in text and sleeps == [0.5]


class Raw(BaseHTTPRequestHandler):
    status = 200
    body = b"{}"

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        return


def raw_server(status, body):
    handler = type("H", (Raw,), {"status": status, "body": body})
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.mark.parametrize(
    "status,body,exc,retried",
    [
        (400, b'{"error":"bad request"}', LLMHTTPError, False),
        (404, b"nope", LLMHTTPError, False),
        (429, b'{"error":"slow down"}', LLMHTTPError, True),
        (200, b"<html>not json</html>", LLMError, False),
        (200, b"[1,2,3]", LLMError, False),
        (200, b'{"choices": []}', LLMError, False),
    ],
)
def test_unusable_responses(status, body, exc, retried):
    httpd = raw_server(status, body)
    try:
        sleeps = []
        cfg = LLMConfig(base_url=f"http://127.0.0.1:{httpd.server_address[1]}/v1", model="m", retries=2)
        agent = LLMAgent(cfg, sleep=sleeps.append)
        with pytest.raises(exc):
            run_trial(make_env("config"), agent, 0)
        assert bool(sleeps) is retried
    finally:
        httpd.shutdown()


def test_http_json_timeout_is_a_connection_error(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", boom)
    with pytest.raises(LLMConnectionError, match="timed out"):
        http_json("http://x/v1/chat/completions", {}, {}, 1.0)


def test_arguments_given_as_an_object_or_empty_string_are_accepted():
    agent = LLMAgent(LLMConfig(base_url="http://x", model="m"))
    from trialgauntlet.models import Action

    agent._tools = ()
    for raw, expected in (({"a": 1}, {"a": 1}), ("", {}), ('{"b": 2}', {"b": 2})):
        action = Action()
        agent._interpret(
            {"content": None, "tool_calls": [{"id": "c", "function": {"name": "t", "arguments": raw}}]}, action
        )
        assert action.tool_call.arguments == expected and action.tool_call.id == "c"


def test_agent_id_ignores_endpoint_and_key_but_not_sampling_settings():
    a = LLMAgent(LLMConfig(base_url="http://a", model="m", api_key="k1"))
    b = LLMAgent(LLMConfig(base_url="http://b", model="m", api_key="k2"))
    c = LLMAgent(LLMConfig(base_url="http://a", model="m", temperature=0.5))
    assert a.agent_id() == b.agent_id() != c.agent_id()
    assert "k1" not in json.dumps(a.config())


def test_flaky_mock_gives_a_pass_at_1_versus_pass_hat_k_gap_and_is_seed_deterministic():
    from trialgauntlet.metrics import aggregate, tally

    with MockServer("flaky", flaky=0.08) as server:
        cfg = LLMConfig(base_url=server.url, model="m")
        a = run_suite(lambda: make_env("config"), lambda: LLMAgent(cfg), list(range(0, 44, 3)), 6, env_spec="config")
        b = run_suite(lambda: make_env("config"), lambda: LLMAgent(cfg), list(range(0, 44, 3)), 6, env_spec="config")
    assert [r.passed for r in a] == [r.passed for r in b]
    agg = aggregate(tally(a), 4)
    assert 0.3 < agg["pass@1"] < 0.95 and agg["pass^k"] < agg["pass@1"] - 0.1


def test_resumed_llm_runs_make_no_new_requests_and_trajectories_replay_offline(tmp_path):
    with MockServer("oracle") as server:
        cfg = LLMConfig(base_url=server.url, model="m")
        run_suite(lambda: make_env("ledger"), lambda: LLMAgent(cfg), [0, 1], 2, env_spec="ledger", run_dir=tmp_path)
        count = len(server.requests)
        assert count > 0
        run_suite(lambda: make_env("ledger"), lambda: LLMAgent(cfg), [0, 1], 2, env_spec="ledger", run_dir=tmp_path)
        assert len(server.requests) == count
    assert replay_trajectory(trajectory_path(tmp_path, "ledger", 1, 1)).ok  # the server is gone


def test_trajectory_records_usage_and_latency(tmp_path):
    with MockServer("oracle") as server:
        agent, _ = agent_for(server)
        path = tmp_path / "t.jsonl"
        run_trial(make_env("config"), agent, 0, env_spec="config", recorder=TrajectoryWriter(path))
    from trialgauntlet.trajectory import read_trajectory

    traj = read_trajectory(path)
    assert all(s["action"]["usage"]["prompt_tokens"] > 0 for s in traj.steps)
    assert traj.header["agent"]["config"]["model"] == "example-model"


# ---------------------------------------------------------------------- text tool-call parsing
TOOLS = (
    ToolSpec(
        "set_key",
        "",
        object_schema({"path": {"type": "string"}, "count": {"type": "integer"}, "on": {"type": "boolean"}}),
    ),
)


@pytest.mark.parametrize(
    "text,name,args",
    [
        ('<tool_call>\n{"name": "peek", "arguments": {"a": 1}}\n</tool_call>', "peek", {"a": 1}),
        ('Sure.\n<tool_call>{"name":"peek","arguments":"{\\"a\\": 2}"}</tool_call>', "peek", {"a": 2}),
        (
            "<tool_call><function=set_key><parameter=path>x.ini</parameter><parameter=count>3</parameter>"
            "<parameter=on>true</parameter></function></tool_call>",
            "set_key",
            {"path": "x.ini", "count": 3, "on": True},
        ),
        ('```json\n{"name": "peek", "arguments": {}}\n```', "peek", {}),
        ('{"tool": "peek", "parameters": {"z": 1}}', "peek", {"z": 1}),
        (
            '<think>{"name":"wrong","arguments":{}}</think><tool_call>{"name":"right","arguments":{}}</tool_call>',
            "right",
            {},
        ),
    ],
)
def test_parse_text_tool_call_formats(text, name, args):
    call = parse_text_tool_call(text, TOOLS)
    assert call is not None and call.name == name and call.arguments == args


@pytest.mark.parametrize(
    "text", ["just prose", "<tool_call>{broken</tool_call>", '{"name": 5}', '{"name":"x","arguments":"[1"}', ""]
)
def test_unparseable_text_returns_none(text):
    assert parse_text_tool_call(text, TOOLS) is None


def test_looks_like_text_tool_call():
    assert looks_like_text_tool_call("<tool_call>...")
    assert looks_like_text_tool_call("<function=a><parameter=b>1</parameter></function>")
    assert not looks_like_text_tool_call("I think we should restart the service.")


# ----------------------------------------------------------------------------------- mock server
def test_mock_server_basics():
    with pytest.raises(ValueError, match="unknown mock mode"):
        MockServer("sorcery")
    assert set(MODES) >= {"oracle", "flaky", "refuse", "noop", "text", "malformed", "parallel", "http500"}
    with MockServer("oracle") as server:
        doc = http_json(models_url(server.url), None, {}, 5, "GET")
        assert doc["data"][0]["id"] == "mock-model"
        with pytest.raises(LLMHTTPError) as exc:
            http_json(server.url + "/nope", {}, {}, 5)
        assert exc.value.status == 404
        resp = http_json(chat_url(server.url), {"model": "m", "messages": [], "tools": []}, {}, 5)
        assert resp["system_fingerprint"] == "trialgauntlet-mock"


def test_infer_env_and_oracle_replay_are_stateless_functions_of_the_transcript():
    assert (
        infer_env({"list_hosts"}) == "fleet"
        and infer_env({"issue_refund"}) == "ledger"
        and infer_env({"set_key"}) == "config"
    )
    with pytest.raises(ValueError):
        infer_env({"echo"})
    env = make_env("config")
    first = env.reset(0)
    tools = [t.to_openai() for t in env.tools()]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": first}]
    name, args = oracle_next_action(msgs, tools)
    assert name == "read_file"
    again = oracle_next_action(msgs, tools)
    assert again == (name, args)
    env_step = env.step(__import__("trialgauntlet.models", fromlist=["ToolCall"]).ToolCall(name, args)).observation
    msgs += [{"role": "assistant", "content": None}, {"role": "tool", "content": env_step}]
    assert oracle_next_action(msgs, tools)[0] == "list_files"
