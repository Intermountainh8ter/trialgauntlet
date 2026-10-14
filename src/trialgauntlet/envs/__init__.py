"""Environment registry."""

from __future__ import annotations

from collections.abc import Callable

from trialgauntlet.protocols import Environment

ENV_FACTORIES: dict[str, Callable[[], Environment]] = {}


def register(name: str, factory: Callable[[], Environment]) -> None:
    ENV_FACTORIES[name] = factory


def env_names() -> list[str]:
    return list(ENV_FACTORIES)


def make_env(spec: str) -> Environment:
    """Build an environment from a spec string. Wrapped variants use ``+`` (see wrappers)."""
    base = spec.split("+", 1)[0]
    if base not in ENV_FACTORIES:
        raise KeyError(f"unknown environment '{base}'. known: {', '.join(sorted(ENV_FACTORIES)) or '(none)'}")
    return ENV_FACTORIES[base]()
