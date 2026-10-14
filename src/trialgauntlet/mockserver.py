"""A mock OpenAI-compatible chat server for testing the LLM adapter. Every run against it is MOCK.

It never loads a model. In ``oracle`` mode it re-runs the environment's scripted oracle from the
transcript in each request (the oracle is a deterministic function of the observations it has seen),
so a whole end-to-end run through the real HTTP path scores 100% unless a failure mode is switched on.
Responses carry ``system_fingerprint: "trialgauntlet-mock"`` so result files are labelled MOCK
automatically.

Modes
    oracle     correct tool calls (the scripted oracle)
    flaky      oracle, but each step fails with probability ``flaky`` (escalates wrongly); seeded by the
               request ``seed`` so trials differ and pass^k < pass@1
    refuse     always calls ``escalate`` with the first category
    noop       replies in prose, never calls a tool
    text       the oracle's call written as text (what a server without --jinja does)
    malformed  a tool call whose arguments are not valid JSON
    parallel   two tool calls in one reply (the adapter must keep only the first)
    http500    the first ``fail_first`` requests fail with HTTP 500, then oracle
"""

from __future__ import annotations

import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from trialgauntlet.models import EpisodeContext, ToolSpec
from trialgauntlet.seeds import derive_seed

MODES = ("oracle", "flaky", "refuse", "noop", "text", "malformed", "parallel", "http500")
FINGERPRINT = "trialgauntlet-mock"


def infer_env(tool_names: set[str]) -> str:
    """Which built-in environment a tool list belongs to."""
    if "list_hosts" in tool_names:
        return "fleet"
    if "issue_refund" in tool_names:
        return "ledger"
    if "set_key" in tool_names:
        return "config"
    raise ValueError("the request's tools do not belong to a built-in environment")


def oracle_next_action(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]] | None:
    """Re-run the scripted oracle over the transcript and return its next (tool, arguments), or None."""
    from trialgauntlet.envs import ORACLES

    names = {t["function"]["name"] for t in tools}
    env = infer_env(names)
    agent = ORACLES[env]()
    specs = tuple(ToolSpec(t["function"]["name"], "", t["function"].get("parameters", {})) for t in tools)
    agent.start(EpisodeContext(env, 0, 0, 0, specs, "", 0))
    # The first user message is the task; later user messages (format-error or nudge feedback) are not
    # environment observations and must not advance the scripted oracle.
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    observations = ([first_user.get("content") or ""] if first_user else []) + [
        m.get("content") or "" for m in messages if m.get("role") == "tool"
    ]
    action = None
    for obs in observations:
        action = agent.act(obs)
    if action is None or action.tool_call is None:
        return None
    return action.tool_call.name, action.tool_call.arguments


class MockServer:
    def __init__(self, mode: str = "oracle", flaky: float = 0.05, fail_first: int = 2) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mock mode '{mode}'. known: {', '.join(MODES)}")
        self.mode = mode
        self.flaky = flaky
        self.fail_first = fail_first
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self._count = 0
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self, port: int = 0, host: str = "127.0.0.1") -> MockServer:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silence
                return

            def _send(self, status: int, doc: dict[str, Any]) -> None:
                data = json.dumps(doc).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/").endswith("/models"):
                    self._send(200, {"object": "list", "data": [{"id": "mock-model", "object": "model"}]})
                elif self.path.rstrip("/") in ("", "/health"):
                    self._send(200, {"status": "ok"})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self.path.rstrip("/").endswith("/chat/completions"):
                    self._send(404, {"error": "not found"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    body = json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    self._send(400, {"error": "invalid JSON"})
                    return
                status, doc = server.handle(body, dict(self.headers.items()))
                self._send(status, doc)

        self._httpd = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def url(self) -> str:
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> MockServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ------------------------------------------------------------------ behaviour
    def handle(self, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        with self._lock:
            self._count += 1
            index = self._count
            self.requests.append(body)
            self.headers.append(headers)
        if self.mode == "http500" and index <= self.fail_first:
            return 500, {"error": {"message": "mock server overloaded"}}
        messages, tools = body.get("messages", []), body.get("tools", [])
        reply = self._reply(messages, tools, body)
        prompt_tokens = len(json.dumps(messages)) // 4
        completion_tokens = max(1, len(json.dumps(reply)) // 4)
        return 200, {
            "id": f"mock-{index}",
            "object": "chat.completion",
            "model": body.get("model", "mock-model"),
            "system_fingerprint": FINGERPRINT,
            "choices": [{"index": 0, "finish_reason": "stop", "message": reply}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        }

    @staticmethod
    def _tool_call(name: str, args: dict[str, Any] | str, n: int) -> dict[str, Any]:
        raw = args if isinstance(args, str) else json.dumps(args)
        return {"id": f"mock_call_{n}", "type": "function", "function": {"name": name, "arguments": raw}}

    def _refusal(self, tools: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        spec = next(t["function"] for t in tools if t["function"]["name"] == "escalate")
        category = spec["parameters"]["properties"]["category"]["enum"][0]
        return "escalate", {"category": category, "entity_id": "n/a", "reason": "mock refusal"}

    def _reply(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], body: dict[str, Any]
    ) -> dict[str, Any]:
        steps = sum(1 for m in messages if m.get("role") == "tool")
        if self.mode == "noop":
            return {"role": "assistant", "content": "I will not take any action."}
        if self.mode == "refuse":
            name, args = self._refusal(tools)
            return {"role": "assistant", "content": None, "tool_calls": [self._tool_call(name, args, steps + 1)]}
        nxt = oracle_next_action(messages, tools)
        if nxt is None:
            return {"role": "assistant", "content": "Done."}
        name, args = nxt
        if self.mode == "flaky":
            rng = random.Random(derive_seed("mock-flaky", body.get("seed"), steps))
            if rng.random() < self.flaky:
                name, args = self._refusal(tools)
        if self.mode == "text":
            text = json.dumps({"name": name, "arguments": args})
            return {"role": "assistant", "content": f"<tool_call>\n{text}\n</tool_call>"}
        if self.mode == "malformed":
            return {"role": "assistant", "content": None, "tool_calls": [self._tool_call(name, "{not json", steps + 1)]}
        calls = [self._tool_call(name, args, steps + 1)]
        if self.mode == "parallel":
            calls.append(self._tool_call(name, args, steps + 2))
        return {"role": "assistant", "content": None, "tool_calls": calls}


def serve(mode: str, port: int, flaky: float, fail_first: int) -> None:  # pragma: no cover - blocking CLI helper
    server = MockServer(mode, flaky=flaky, fail_first=fail_first).start(port=port)
    print(f"MOCK server ({mode}) listening on {server.url}  (responses are scripted; results are labelled MOCK)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()
