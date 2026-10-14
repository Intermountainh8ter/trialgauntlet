"""Name -> agent factory for the built-in non-LLM agents."""

from __future__ import annotations

from collections.abc import Callable

from trialgauntlet.agents.baselines import AlwaysRefuseAgent, NoOpAgent, RandomToolAgent
from trialgauntlet.protocols import Agent

# CLI name -> display name
DISPLAY = {
    "noop": "no-op",
    "random": "random-tool",
    "refuse": "always-refuse",
    "oracle": "scripted-oracle",
    "greedy": "greedy-unsafe",
}
TRIVIAL = ("noop", "random", "refuse")
BASELINES = tuple(DISPLAY)


def make_baseline(name: str, env_name: str) -> Callable[[], Agent]:
    """Factory for a baseline agent; ``oracle`` and ``greedy`` are environment-specific."""
    from trialgauntlet.envs import GREEDY, ORACLES

    if name == "noop":
        return NoOpAgent
    if name == "random":
        return RandomToolAgent
    if name == "refuse":
        return AlwaysRefuseAgent
    table = {"oracle": ORACLES, "greedy": GREEDY}
    if name in table:
        base = env_name.split("+", 1)[0]
        if base not in table[name]:
            raise KeyError(f"no {name} agent for environment '{base}'")
        return table[name][base]
    raise KeyError(f"unknown baseline '{name}'. known: {', '.join(BASELINES)}")
