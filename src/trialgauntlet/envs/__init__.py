"""Environment registry."""

from __future__ import annotations

from collections.abc import Callable

from trialgauntlet.protocols import Agent, Environment

ENV_FACTORIES: dict[str, Callable[[], Environment]] = {}
# Per-environment reference agents (filled by the environment modules).
ORACLES: dict[str, Callable[[], Agent]] = {}
GREEDY: dict[str, Callable[[], Agent]] = {}


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


def _register_builtin() -> None:
    from trialgauntlet.envs.config import ConfigEnv, ConfigGreedy, ConfigOracle
    from trialgauntlet.envs.fleet import FleetEnv, FleetGreedy, FleetOracle
    from trialgauntlet.envs.ledger import LedgerEnv, LedgerGreedy, LedgerOracle

    for name, env, oracle, greedy in (
        ("fleet", FleetEnv, FleetOracle, FleetGreedy),
        ("ledger", LedgerEnv, LedgerOracle, LedgerGreedy),
        ("config", ConfigEnv, ConfigOracle, ConfigGreedy),
    ):
        register(name, env)
        ORACLES[name] = oracle
        GREEDY[name] = greedy


_register_builtin()
