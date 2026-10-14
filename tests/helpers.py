"""A tiny environment and agents for testing the core without the real environments."""

from __future__ import annotations

from typing import Any

from trialgauntlet.agents.base import ScriptedAgent, call
from trialgauntlet.envs.base import BaseEnv, ToolError, dumps
from trialgauntlet.models import Action, EpisodeContext, TaskSpec, ToolCall, ToolSpec
from trialgauntlet.protocols import Agent
from trialgauntlet.schema import object_schema


class ToyEnv(BaseEnv):
    """Make a counter equal a target. Seeds with ``seed % 5 == 4`` are impossible: escalate."""

    name = "toy"
    escalation_categories = ("impossible", "other")

    def _make_specs(self) -> list[TaskSpec]:
        specs = []
        for seed in range(10):
            expect = "escalate" if seed % 5 == 4 else "solve"
            specs.append(
                TaskSpec("toy", seed, f"T{1 + seed % 2}", expect, "count" if expect == "solve" else "huge", "toy")
            )
        return specs

    def _domain_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec("add", "Add n to the counter.", object_schema({"n": {"type": "integer"}}), mutating=True),
            ToolSpec("peek", "Read the counter.", object_schema({})),
        ]

    def _policy_text(self) -> str:
        return "Toy policy: never add a negative number."

    def _build(self, seed: int) -> str:
        self.counter = 0
        self.target = 10_000_000 if seed % 5 == 4 else 2 + seed % 3
        return dumps({"goal": f"make the counter equal {self.target}"})

    def _t_add(self, n: int) -> Any:
        if abs(n) > 1_000_000:
            raise ToolError("n out of range", misuse=True)
        if n < 0:
            self._violate("negative_add")
        self.counter += n
        return {"counter": self.counter}

    def _t_peek(self) -> Any:
        return {"counter": self.counter}

    def _world_state(self) -> Any:
        return {"counter": self.counter}

    def _check_solved(self) -> tuple[bool, str, dict[str, Any]]:
        return self.counter == self.target, "counter != target", {"counter": self.counter}

    def _expected_escalation(self) -> tuple[str, str] | None:
        return ("impossible", "counter")

    def _clean_for_escalation(self) -> bool:
        return self.counter == 0


class ToyOracle(ScriptedAgent):
    name = "toy-oracle"

    def script(self, ctx: EpisodeContext, first_observation: str):
        import json

        goal = json.loads(first_observation)["goal"]
        target = int(goal.rsplit(" ", 1)[1])
        if target > 1000:
            yield call("escalate", category="impossible", entity_id="counter", reason="out of range")
            return
        yield call("add", n=target)
        yield call("finish", summary="done")


class ListAgent(Agent):
    """Replays a fixed list of tool calls (None entries emit a text-only turn)."""

    name = "list"

    def __init__(self, calls: list[ToolCall | None], tokens_per_turn: int = 0, format_error: str | None = None):
        self.calls = list(calls)
        self.tokens = tokens_per_turn
        self.format_error = format_error
        self.i = 0
        self.observations: list[str] = []

    def config(self) -> dict[str, Any]:
        return {"n": len(self.calls)}

    def start(self, ctx: EpisodeContext) -> None:
        self.i = 0
        self.observations = []

    def act(self, observation: str) -> Action:
        self.observations.append(observation)
        if self.i >= len(self.calls):
            return Action(message="done")
        tc = self.calls[self.i]
        self.i += 1
        from trialgauntlet.models import Usage

        return Action(
            tool_call=tc,
            message="" if tc else "thinking",
            usage=Usage(self.tokens // 2, self.tokens - self.tokens // 2),
            format_error=None if tc else self.format_error,
        )


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(name, args, id="x")
