"""Per-trial budgets: agent turns, tokens and wall-clock seconds."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Budget:
    """Limits for one trial. ``None`` disables a limit.

    ``max_steps`` counts agent turns (tool calls, nudged text turns and format errors alike), so a
    model that never produces a valid call still terminates.
    """

    max_steps: int = 30
    max_tokens: int | None = None
    max_seconds: float | None = None
    max_nudges: int = 1
    max_format_errors: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Budget:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BudgetTracker:
    """Tracks consumption against a :class:`Budget`. ``clock`` is injectable for tests."""

    def __init__(self, budget: Budget, clock: Callable[[], float] = time.monotonic) -> None:
        self.budget = budget
        self._clock = clock
        self._start = clock()
        self.turns = 0
        self.tokens = 0

    @property
    def elapsed(self) -> float:
        return self._clock() - self._start

    def charge_turn(self, tokens: int = 0) -> None:
        self.turns += 1
        self.tokens += tokens

    def exceeded(self, include_steps: bool = True) -> str | None:
        """Name of the first exceeded limit (``steps``, ``tokens`` or ``time``), else ``None``.

        After an agent turn the step limit is not re-checked (``include_steps=False``): the turn
        that reaches the limit is still allowed to execute.
        """
        b = self.budget
        if include_steps and self.turns >= b.max_steps:
            return "steps"
        if b.max_tokens is not None and self.tokens > b.max_tokens:
            return "tokens"
        if b.max_seconds is not None and self.elapsed > b.max_seconds:
            return "time"
        return None
