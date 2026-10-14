"""Agent combinators used to exercise the injection and fault suites."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from trialgauntlet.models import Action, EpisodeContext, ToolCall
from trialgauntlet.protocols import Agent


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def find_embedded_call(observation: str) -> ToolCall | None:
    """First ``{"name": ..., "arguments": {...}}`` object embedded in a text field of an observation."""
    try:
        doc = json.loads(observation)
    except json.JSONDecodeError:
        return None
    decoder = json.JSONDecoder()
    for text in _strings(doc):
        start = text.find("{")
        while start != -1:
            try:
                obj, _ = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict) and isinstance(obj.get("name"), str) and isinstance(obj.get("arguments"), dict):
                return ToolCall(obj["name"], obj["arguments"])
            start = text.find("{", start + 1)
    return None


class GullibleAgent(Agent):
    """Wraps a well-behaved agent but obeys any tool call embedded in a tool result.

    It exists to prove the injection grader fires: against an injected environment its attack
    success rate must be close to 100%, against a clean environment it behaves exactly like the
    wrapped agent. Each distinct injected call is followed once.
    """

    def __init__(self, inner: Agent) -> None:
        self.inner = inner
        self.name = f"gullible-{inner.name}"
        self._held: Action | None = None
        self._followed: set[str] = set()
        self._n = 0

    def config(self) -> dict[str, Any]:
        return {"inner": self.inner.name, "inner_config": self.inner.config()}

    def start(self, ctx: EpisodeContext) -> None:
        self.inner.start(ctx)
        self._held = None
        self._followed = set()
        self._n = 0

    def act(self, observation: str) -> Action:
        if self._held is not None:
            action, self._held = self._held, None
            return action
        planned = self.inner.act(observation)
        injected = find_embedded_call(observation)
        if injected is not None:
            key = json.dumps([injected.name, injected.arguments], sort_keys=True)
            if key not in self._followed:
                self._followed.add(key)
                self._held = planned
                self._n += 1
                return Action(tool_call=ToolCall(injected.name, injected.arguments, id=f"inj_{self._n}"))
        return planned


def looks_like_fault(observation: str) -> bool:
    """A tool result that is not a complete JSON document, or one flagged ``retryable``."""
    try:
        doc = json.loads(observation)
    except json.JSONDecodeError:
        return True
    return isinstance(doc, dict) and doc.get("retryable") is True


class RetryAgent(Agent):
    """Wraps an agent and re-issues the previous call when the result looks like a transient fault."""

    def __init__(self, inner: Agent, max_attempts: int = 3) -> None:
        self.inner = inner
        self.max_attempts = max_attempts
        self.name = f"{inner.name}-retry"
        self._last: Action | None = None
        self._attempts = 0

    def config(self) -> dict[str, Any]:
        return {"inner": self.inner.name, "inner_config": self.inner.config(), "max_attempts": self.max_attempts}

    def start(self, ctx: EpisodeContext) -> None:
        self.inner.start(ctx)
        self._last = None
        self._attempts = 0

    def act(self, observation: str) -> Action:
        last = self._last.tool_call if self._last is not None else None
        if last is not None and self._attempts < self.max_attempts and looks_like_fault(observation):
            self._attempts += 1
            self._last = Action(tool_call=ToolCall(last.name, last.arguments, id=f"{last.id}_r{self._attempts}"))
            return self._last
        self._attempts = 0
        self._last = self.inner.act(observation)
        return self._last
