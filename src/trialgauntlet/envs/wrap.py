"""Environment wrappers and the ``base+modifier=arg`` spec grammar."""

from __future__ import annotations

from collections.abc import Callable

from trialgauntlet.envs.base import BaseEnv
from trialgauntlet.models import Grade, StepResult, TaskSpec, ToolCall, ToolSpec
from trialgauntlet.protocols import Environment

WRAPPERS: dict[str, Callable[[Environment, str | None], Environment]] = {}


def parse_spec(spec: str) -> tuple[str, list[tuple[str, str | None]]]:
    """``"fleet+inject=fake_system+fault=timeout"`` -> ``("fleet", [("inject", "fake_system"), ...])``."""
    base, *mods = spec.split("+")
    parsed: list[tuple[str, str | None]] = []
    for mod in mods:
        name, sep, arg = mod.partition("=")
        if not name:
            raise ValueError(f"empty modifier in environment spec '{spec}'")
        parsed.append((name, arg if sep else None))
    return base, parsed


class EnvWrapper(Environment):
    """Delegates everything to ``inner``; subclasses override what they change."""

    def __init__(self, inner: Environment) -> None:
        self.inner = inner
        self.name = inner.name
        self.version = inner.version
        self.default_max_steps = inner.default_max_steps

    @property
    def base(self) -> BaseEnv:
        env: Environment = self.inner
        while isinstance(env, EnvWrapper):
            env = env.inner
        assert isinstance(env, BaseEnv)
        return env

    def task_specs(self) -> list[TaskSpec]:
        return self.inner.task_specs()

    def reset(self, seed: int, trial: int = 0) -> str:
        return self.inner.reset(seed, trial)

    def tools(self) -> list[ToolSpec]:
        return self.inner.tools()

    def system_prompt(self) -> str:
        return self.inner.system_prompt()

    def step(self, call: ToolCall) -> StepResult:
        return self.inner.step(call)

    def grade(self) -> Grade:
        return self.inner.grade()

    def state_digest(self) -> str:
        return self.inner.state_digest()

    def extra_metrics(self) -> dict[str, object]:
        return self.inner.extra_metrics()


class NaiveGraded(EnvWrapper):
    """Swap in :meth:`BaseEnv.naive_grade`: unsolvable tasks pass when nothing changed."""

    def grade(self) -> Grade:
        return self.base.naive_grade()


WRAPPERS["naive"] = lambda env, arg: NaiveGraded(env)
