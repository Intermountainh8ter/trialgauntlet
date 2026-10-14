"""Building blocks for scripted (non-LLM) agents."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Generator
from typing import Any

from trialgauntlet.models import Action, EpisodeContext, ToolCall
from trialgauntlet.protocols import Agent

Script = Generator[ToolCall, str, None]


def call(name: str, **arguments: Any) -> ToolCall:
    """Shorthand used by scripts: ``obs = yield call("get_host", host="web-01")``."""
    return ToolCall(name=name, arguments=arguments)


class ScriptedAgent(Agent):
    """An agent written as a generator.

    ``script`` receives the context and the first observation, yields tool calls and receives each
    resulting observation. When the generator ends the agent stops calling tools. Scripts must be
    deterministic functions of the observations they see, which is what lets the mock LLM server
    re-run them statelessly from a transcript.
    """

    name = "scripted"

    def __init__(self) -> None:
        self._ctx: EpisodeContext | None = None
        self._gen: Script | None = None
        self._count = 0
        self._gave_up = False

    @abstractmethod
    def script(self, ctx: EpisodeContext, first_observation: str) -> Script: ...

    def start(self, ctx: EpisodeContext) -> None:
        self._ctx = ctx
        self._gen = None
        self._count = 0
        self._gave_up = False

    def act(self, observation: str) -> Action:
        assert self._ctx is not None, "start() must be called first"
        if self._gave_up:
            return Action()
        try:
            if self._gen is None:
                self._gen = self.script(self._ctx, observation)
                tc = next(self._gen)
            else:
                tc = self._gen.send(observation)
        except StopIteration:
            return Action()
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as err:
            # A brittle script that cannot parse an unexpected observation (an error document, a
            # truncated tool result) gives up, like a naive agent would.
            self._gave_up = True
            return Action(message=f"script could not handle the observation: {err!r}")
        self._count += 1
        return Action(tool_call=ToolCall(tc.name, dict(tc.arguments), id=f"call_{self._count}"))
