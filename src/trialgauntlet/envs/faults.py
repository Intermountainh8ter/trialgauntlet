"""Fault-injection suite: tool timeouts, malformed outputs, transient errors, lost responses.

``FaultedEnv`` wraps any environment. For every eligible tool call a seeded generator decides
whether to inject a fault. A call that has just failed is faulted at most ``MAX_CONSECUTIVE`` times
in a row, so an agent that retries a failed call three times always gets through; a plain agent
that does not retry usually does not. Recovery is reported through ``extra_metrics``.

Profiles
    transient     503 response, the call is not applied
    timeout       deadline exceeded, the call is not applied
    malformed     the result of a read-only call is truncated (invalid JSON); the call is applied
    lost_response a state-changing call is applied but its response is replaced by a timeout error
    mixed         each fault is drawn from the four above
"""

from __future__ import annotations

import json
import random
from typing import Any

from trialgauntlet.envs.base import dumps
from trialgauntlet.envs.wrap import WRAPPERS, EnvWrapper
from trialgauntlet.models import StepResult, ToolCall
from trialgauntlet.protocols import Environment
from trialgauntlet.seeds import derive_seed

PROFILES = ("transient", "timeout", "malformed", "lost_response", "mixed")
DEFAULT_RATE = 0.25
MAX_CONSECUTIVE = 2

TRANSIENT = dumps({"error": "service_unavailable", "status": 503, "retryable": True})
TIMEOUT = dumps({"error": "timeout", "detail": "tool call exceeded its 30s deadline", "retryable": True})


class FaultedEnv(EnvWrapper):
    def __init__(self, inner: Environment, profile: str, rate: float = DEFAULT_RATE) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown fault profile '{profile}'. known: {', '.join(PROFILES)}")
        if not 0.0 <= rate <= 1.0:
            raise ValueError("fault rate must be between 0 and 1")
        super().__init__(inner)
        self.profile = profile
        self.rate = rate
        self._rng = random.Random(0)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.injected = 0
        self.by_kind: dict[str, int] = {}
        self.retries = 0
        self._consecutive = 0
        self._last_faulted: str | None = None
        self._mutating = {t.name for t in self.inner.tools() if t.mutating}
        self._terminal = {t.name for t in self.inner.tools() if t.terminal}

    def reset(self, seed: int, trial: int = 0) -> str:
        self._rng = random.Random(derive_seed("fault", self.profile, seed, trial))
        self._reset_counters()
        return self.inner.reset(seed, trial)

    def _choose(self, name: str) -> str | None:
        """The fault to inject into this call, or None."""
        if name in self._terminal or self._rng.random() >= self.rate:
            return None
        mutating = name in self._mutating
        if self.profile == "mixed":
            kinds = ["transient", "timeout", "lost_response" if mutating else "malformed"]
            return self._rng.choice(kinds)
        if self.profile == "malformed" and mutating:
            return None
        if self.profile == "lost_response" and not mutating:
            return None
        return self.profile

    def step(self, call: ToolCall) -> StepResult:
        key = json.dumps([call.name, call.arguments], sort_keys=True)
        if key == self._last_faulted:
            self.retries += 1
        kind = self._choose(call.name) if self._consecutive < MAX_CONSECUTIVE or key != self._last_faulted else None
        if kind is None:
            self._consecutive = 0
            self._last_faulted = None
            return self.inner.step(call)
        self.injected += 1
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
        self._consecutive = self._consecutive + 1 if key == self._last_faulted else 1
        self._last_faulted = key
        if kind == "transient":
            return StepResult(TRANSIENT, is_error=True)
        if kind == "timeout":
            return StepResult(TIMEOUT, is_error=True)
        result = self.inner.step(call)
        if kind == "lost_response":
            return StepResult(TIMEOUT, done=result.done, is_error=True)
        cut = max(1, int(len(result.observation) * 0.6))
        return StepResult(result.observation[:cut], done=result.done, is_error=True)

    def extra_metrics(self) -> dict[str, Any]:
        return {
            **self.inner.extra_metrics(),
            "fault_profile": self.profile,
            "faults_injected": self.injected,
            "faults_by_kind": dict(sorted(self.by_kind.items())),
            "retries_after_fault": self.retries,
        }


def _make(env: Environment, arg: str | None) -> Environment:
    if arg is None:
        raise ValueError(f"fault needs a profile, e.g. fault=mixed:0.3. known: {', '.join(PROFILES)}")
    profile, _, rate = arg.partition(":")
    return FaultedEnv(env, profile, float(rate) if rate else DEFAULT_RATE)


WRAPPERS["fault"] = _make
