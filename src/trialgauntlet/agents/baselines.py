"""Trivial baseline agents. Every environment must be audited against all three."""

from __future__ import annotations

import contextlib
import json
import random
from typing import Any

from trialgauntlet.models import Action, EpisodeContext, ToolCall, ToolSpec
from trialgauntlet.protocols import Agent


class NoOpAgent(Agent):
    """Never calls a tool. Models an agent that stalls, apologises or answers in prose."""

    name = "no-op"

    def start(self, ctx: EpisodeContext) -> None:
        pass

    def act(self, observation: str) -> Action:
        return Action(message="I will not take any action.")


class AlwaysRefuseAgent(Agent):
    """Calls ``escalate`` immediately with fixed arguments (first category, no entity)."""

    name = "always-refuse"

    def __init__(self) -> None:
        self._call: ToolCall | None = None
        self._sent = False

    def start(self, ctx: EpisodeContext) -> None:
        spec = next(t for t in ctx.tools if t.name == "escalate")
        category = spec.parameters["properties"]["category"]["enum"][0]
        self._call = ToolCall("escalate", {"category": category, "entity_id": "n/a", "reason": "refused"}, id="call_1")
        self._sent = False

    def act(self, observation: str) -> Action:
        if self._sent:
            return Action()
        self._sent = True
        return Action(tool_call=self._call)


def _harvest(value: Any, out: list[str]) -> None:
    """Collect short string values (identifiers, statuses, names) from a JSON document."""
    if isinstance(value, str):
        if 0 < len(value) <= 40 and "\n" not in value and value not in out:
            out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            _harvest(item, out)
    elif isinstance(value, list):
        for item in value:
            _harvest(item, out)


class RandomToolAgent(Agent):
    """Uniformly random tool, schema-typed random arguments.

    Argument values come from the schema (enums, integer ranges) and from a vocabulary of short
    strings the agent has seen in earlier observations, so it can stumble on real identifiers. It
    reads nothing else about the environment. Deterministic given the trial seed.
    """

    name = "random-tool"

    def __init__(self) -> None:
        self._rng = random.Random(0)
        self._tools: tuple[ToolSpec, ...] = ()
        self._vocab: list[str] = []
        self._n = 0

    def start(self, ctx: EpisodeContext) -> None:
        self._rng = random.Random(ctx.trial_seed)
        self._tools = ctx.tools
        self._vocab = []
        self._n = 0

    def _value(self, schema: dict[str, Any]) -> Any:
        rng = self._rng
        if "enum" in schema:
            return rng.choice(schema["enum"])
        kind = schema.get("type")
        if kind == "integer":
            lo, hi = schema.get("minimum", 0), schema.get("maximum", 10)
            if hi - lo > 50:
                return rng.choice([lo, lo + 1, 5, 100, 1000])
            return rng.randint(lo, hi)
        if kind == "number":
            return rng.random() * 10
        if kind == "boolean":
            return rng.random() < 0.5
        if kind == "array":
            return [self._value(schema.get("items", {"type": "string"})) for _ in range(rng.randint(0, 2))]
        if self._vocab and rng.random() < 0.85:
            return rng.choice(self._vocab)
        return rng.choice(["x", "test", "1"])

    def act(self, observation: str) -> Action:
        with contextlib.suppress(json.JSONDecodeError):
            _harvest(json.loads(observation), self._vocab)
        tool = self._rng.choice(self._tools)
        props = tool.parameters.get("properties", {})
        required = set(tool.parameters.get("required", []))
        args = {name: self._value(spec) for name, spec in props.items() if name in required or self._rng.random() < 0.5}
        self._n += 1
        return Action(tool_call=ToolCall(tool.name, args, id=f"call_{self._n}"))
