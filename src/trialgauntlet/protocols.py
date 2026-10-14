"""The two protocols everything else is built on: :class:`Environment` and :class:`Agent`."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

from trialgauntlet.models import (
    Action,
    EpisodeContext,
    Grade,
    StepResult,
    TaskSpec,
    ToolCall,
    ToolSpec,
)


def canonical_json(obj: Any) -> str:
    """Canonical JSON used for state digests: sorted keys, no whitespace, ASCII only."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


class Environment(ABC):
    """A deterministic, seeded, verifiable-by-final-state task environment.

    Lifecycle: ``reset(seed)`` builds the world for one task and returns the first observation;
    ``step(call)`` applies a tool call; the episode ends when a step returns ``done=True`` or the
    runner stops it; ``grade()`` reads the final state and the call log.

    ``trial`` is passed to ``reset`` only so wrappers (fault injection) can vary per trial. Built-in
    environments ignore it: they are a pure function of ``seed``.
    """

    name: str = "env"
    version: str = "1"
    default_max_steps: int = 30

    @abstractmethod
    def task_specs(self) -> list[TaskSpec]:
        """All tasks of this environment, in seed order."""

    def task_seeds(self) -> list[int]:
        return [t.seed for t in self.task_specs()]

    def task(self, seed: int) -> TaskSpec:
        for spec in self.task_specs():
            if spec.seed == seed:
                return spec
        raise KeyError(f"{self.name}: no task with seed {seed}")

    @abstractmethod
    def reset(self, seed: int, trial: int = 0) -> str:
        """Build the world for task ``seed``; return the first observation (a JSON string)."""

    @abstractmethod
    def tools(self) -> list[ToolSpec]:
        """The tool schema (identical for every task of the environment)."""

    @abstractmethod
    def system_prompt(self) -> str:
        """Policy text and instructions shown to the agent."""

    @abstractmethod
    def step(self, call: ToolCall) -> StepResult:
        """Apply one tool call."""

    @abstractmethod
    def grade(self) -> Grade:
        """Grade the current (final) state and call log."""

    @abstractmethod
    def state_digest(self) -> str:
        """SHA-256 of the canonical world state."""

    def extra_metrics(self) -> dict[str, Any]:
        """Per-trial extra measurements (attack success, faults injected, ...)."""
        return {}


class Agent(ABC):
    """Anything that can turn observations into tool calls."""

    name: str = "agent"

    def config(self) -> dict[str, Any]:
        """JSON-able configuration; hashed into the agent id so resumed runs cannot mix agents."""
        return {}

    def agent_id(self) -> str:
        return f"{self.name}-{digest_of(self.config())[:8]}"

    @abstractmethod
    def start(self, ctx: EpisodeContext) -> None:
        """Called once per trial before the first observation."""

    @abstractmethod
    def act(self, observation: str) -> Action:
        """Return the next action. The first call receives the task's initial observation."""

    def close(self) -> None:  # pragma: no cover - optional hook
        return None
