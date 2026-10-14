"""OpenAI-compatible tool-calling agent over plain ``urllib`` (no third-party client).

Works with any server that implements ``POST /v1/chat/completions`` with ``tools``: llama.cpp
``llama-server --jinja``, vLLM, Ollama's OpenAI endpoint, or a hosted service. The adapter

* sends the environment's tool schema and the policy as the system prompt,
* passes the per-trial seed and the temperature on every request,
* retries connection resets, timeouts, HTTP 429 and 5xx with exponential backoff,
* records token usage and per-request latency,
* turns malformed arguments and tool calls written as text into explicit ``format_error`` actions
  instead of silently accepting or silently dropping them.

It does not enable text-mode tool parsing unless asked (``parse_text_tools``): a server launched
without ``--jinja`` returns tool calls as plain text, and the honest outcome of that is a loud
format error, not a quietly lenient score.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trialgauntlet.models import Action, EpisodeContext, ToolCall, ToolSpec, Usage
from trialgauntlet.protocols import Agent

SYSTEM_SUFFIX = (
    "\n\nCall exactly one tool per reply, using the tool-calling interface. Do not describe a tool call in "
    "prose. Finish with `finish` or `escalate`."
)
MOCK_FINGERPRINT_PREFIX = "trialgauntlet-mock"


class LLMError(Exception):
    """The model server could not produce a usable response."""


class LLMConnectionError(LLMError):
    """The server could not be reached at all."""


class LLMHTTPError(LLMError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status} from the model server: {body[:300]}")
        self.status = status
        self.body = body


def chat_url(base_url: str) -> str:
    """``http://host:8080``, ``http://host:8080/v1`` and a full ``.../chat/completions`` URL all work."""
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if not url.endswith("/v1"):
        url += "/v1"
    return url + "/chat/completions"


def models_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    if not url.endswith("/v1"):
        url += "/v1"
    return url + "/models"


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str | None = None
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = 1024
    timeout: float = 120.0
    retries: int = 3
    backoff: float = 0.5
    parse_text_tools: bool = False
    extra_body: dict[str, Any] = field(default_factory=dict)


def http_json(
    url: str, payload: dict[str, Any] | None, headers: dict[str, str], timeout: float, method: str = "POST"
) -> dict[str, Any]:
    """One HTTP round trip returning decoded JSON. Raises LLMHTTPError / LLMConnectionError."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme is user supplied http(s)
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        raise LLMHTTPError(err.code, err.read().decode("utf-8", "replace")) from err
    except urllib.error.URLError as err:
        raise LLMConnectionError(_connection_message(url, err.reason)) from err
    except TimeoutError as err:
        raise LLMConnectionError(f"timed out after {timeout:g}s waiting for {url}") from err
    except (ConnectionError, OSError) as err:
        raise LLMConnectionError(_connection_message(url, err)) from err
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as err:
        raise LLMError(f"the server at {url} did not return JSON: {body[:200]!r}") from err
    if not isinstance(doc, dict):
        raise LLMError(f"unexpected JSON from {url}: {body[:200]!r}")
    return doc


def _connection_message(url: str, reason: object) -> str:
    text = str(reason)
    msg = f"cannot reach {url} ({text})"
    if "refused" in text.lower():
        msg += (
            ": connection refused, nothing is listening there. Start the server "
            "(for llama.cpp: llama-server --jinja ...) or fix --base-url"
        )
    return msg


# ------------------------------------------------------------------------- text tool-call parsing
_THINK = re.compile(r"<think>.*?</think>", re.S)
_HERMES = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
_XML_CALL = re.compile(r"<function=([\w.\-]+)>(.*?)</function>", re.S)
_XML_PARAM = re.compile(r"<parameter=([\w.\-]+)>\s*(.*?)\s*</parameter>", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _coerce(value: str, schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
        if kind == "boolean":
            return value.strip().lower() in ("true", "1", "yes")
        if kind in ("array", "object"):
            return json.loads(value)
    except (ValueError, json.JSONDecodeError):
        return value
    return value


def parse_text_tool_call(text: str, tools: tuple[ToolSpec, ...]) -> ToolCall | None:
    """Best-effort parse of a tool call that a server returned as text (Hermes JSON, Qwen XML, bare JSON)."""
    text = _THINK.sub("", text)
    names = {t.name: t for t in tools}
    for pattern in (_HERMES, _FENCE):
        for m in pattern.finditer(text):
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            call = _from_object(obj)
            if call:
                return call
    m = _XML_CALL.search(text)
    if m:
        name = m.group(1)
        props = names[name].parameters.get("properties", {}) if name in names else {}
        args = {k: _coerce(v, props.get(k, {})) for k, v in _XML_PARAM.findall(m.group(2))}
        return ToolCall(name, args)
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return _from_object(json.loads(stripped))
        except json.JSONDecodeError:
            return None
    return None


def _from_object(obj: Any) -> ToolCall | None:
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("tool")
    args = obj.get("arguments", obj.get("parameters", obj.get("args", {})))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if isinstance(name, str) and isinstance(args, dict):
        return ToolCall(name, args)
    return None


def looks_like_text_tool_call(text: str) -> bool:
    return bool(_HERMES.search(text) or _XML_CALL.search(text) or "<tool_call>" in text or _FENCE.search(text))


# ------------------------------------------------------------------------------------------ agent
class LLMAgent(Agent):
    def __init__(
        self,
        config: LLMConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = config
        self.name = config.model
        self._sleep = sleep
        self._clock = clock
        self._messages: list[dict[str, Any]] = []
        self._tools: tuple[ToolSpec, ...] = ()
        self._tool_payload: list[dict[str, Any]] = []
        self._seed = 0
        self._pending_call_id: str | None = None
        self._n = 0
        self.fingerprints: set[str] = set()
        self.requests = 0
        self.retries_used = 0

    # -- Agent API ----------------------------------------------------------------------------
    def config(self) -> dict[str, Any]:
        c = self.cfg
        return {
            "model": c.model,
            "temperature": c.temperature,
            "top_p": c.top_p,
            "max_tokens": c.max_tokens,
            "parse_text_tools": c.parse_text_tools,
            "extra_body": c.extra_body,
        }

    @property
    def is_mock(self) -> bool:
        return any(f.startswith(MOCK_FINGERPRINT_PREFIX) for f in self.fingerprints)

    def start(self, ctx: EpisodeContext) -> None:
        self._tools = ctx.tools
        self._tool_payload = [t.to_openai() for t in ctx.tools]
        self._messages = [{"role": "system", "content": ctx.system_prompt + SYSTEM_SUFFIX}]
        self._seed = ctx.trial_seed
        self._pending_call_id = None
        self._n = 0

    def act(self, observation: str) -> Action:
        if self._pending_call_id is not None:
            self._messages.append({"role": "tool", "tool_call_id": self._pending_call_id, "content": observation})
        else:
            self._messages.append({"role": "user", "content": observation})
        self._pending_call_id = None
        started = self._clock()
        response = self._complete()
        latency = self._clock() - started
        usage = response.get("usage") or {}
        action = Action(
            usage=Usage(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)),
            latency_s=latency,
        )
        fingerprint = response.get("system_fingerprint")
        if isinstance(fingerprint, str):
            self.fingerprints.add(fingerprint)
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as err:
            raise LLMError(f"response has no choices[0].message: {str(response)[:200]}") from err
        self._interpret(message, action)
        return action

    # -- internals ----------------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}

    def _body(self) -> dict[str, Any]:
        c = self.cfg
        body: dict[str, Any] = {
            "model": c.model,
            "messages": self._messages,
            "tools": self._tool_payload,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "temperature": c.temperature,
            "max_tokens": c.max_tokens,
            "seed": self._seed,
            "stream": False,
        }
        if c.top_p is not None:
            body["top_p"] = c.top_p
        body.update(c.extra_body)
        return body

    def _complete(self) -> dict[str, Any]:
        url = chat_url(self.cfg.base_url)
        body = self._body()
        last: LLMError | None = None
        for attempt in range(self.cfg.retries + 1):
            self.requests += 1
            try:
                return http_json(url, body, self._headers(), self.cfg.timeout)
            except LLMHTTPError as err:
                if err.status not in (408, 409, 425, 429) and err.status < 500:
                    raise
                last = err
            except LLMConnectionError as err:
                last = err
            if attempt < self.cfg.retries:
                self.retries_used += 1
                self._sleep(self.cfg.backoff * (2**attempt))
        assert last is not None
        raise last

    def _interpret(self, message: dict[str, Any], action: Action) -> None:
        content = message.get("content") or ""
        action.message = content
        calls = message.get("tool_calls") or []
        if calls:
            first = calls[0]
            fn = first.get("function") or {}
            name = fn.get("name")
            raw = fn.get("arguments", {})
            call_id = first.get("id") or f"call_{self._n + 1}"
            args: Any = raw
            if isinstance(raw, str):
                try:
                    args = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError:
                    args = None
            if not isinstance(name, str) or not isinstance(args, dict):
                action.format_error = "malformed_arguments"
                self._messages.append({"role": "assistant", "content": content or f"{name}({raw})"})
                return
            self._n += 1
            # keep the history consistent with the single call that is executed
            self._messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                    ],
                }
            )
            self._pending_call_id = call_id
            action.tool_call = ToolCall(name, args, id=call_id)
            return
        self._messages.append({"role": "assistant", "content": content})
        if looks_like_text_tool_call(content):
            parsed = parse_text_tool_call(content, self._tools) if self.cfg.parse_text_tools else None
            if parsed is not None:
                self._n += 1
                call_id = f"call_{self._n}"
                self._messages[-1] = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": parsed.name, "arguments": json.dumps(parsed.arguments)},
                        }
                    ],
                }
                self._pending_call_id = call_id
                action.tool_call = ToolCall(parsed.name, parsed.arguments, id=call_id)
                return
            action.format_error = "tool_call_as_text"
