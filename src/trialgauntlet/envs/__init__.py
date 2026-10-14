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
    """Build an environment from a spec such as ``fleet`` or ``ledger+naive`` (see ``envs.wrap``)."""
    from trialgauntlet.envs.wrap import WRAPPERS, parse_spec

    base, modifiers = parse_spec(spec)
    if base not in ENV_FACTORIES:
        raise KeyError(f"unknown environment '{base}'. known: {', '.join(sorted(ENV_FACTORIES)) or '(none)'}")
    env = ENV_FACTORIES[base]()
    for name, arg in modifiers:
        if name not in WRAPPERS:
            raise KeyError(f"unknown environment modifier '{name}'. known: {', '.join(sorted(WRAPPERS))}")
        env = WRAPPERS[name](env, arg)
    return env


def _register_builtin() -> None:
    from trialgauntlet.envs import faults, inject  # noqa: F401  (register the wrappers)
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
