"""Trial runner: seeded, budgeted, recorded, resumable, replayable."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from trialgauntlet.budget import Budget, BudgetTracker
from trialgauntlet.models import SCHEMA_VERSION, Action, EpisodeContext, TrialResult
from trialgauntlet.protocols import Agent, Environment
from trialgauntlet.seeds import derive_seed
from trialgauntlet.trajectory import (
    MemoryRecorder,
    Trajectory,
    TrajectoryError,
    TrajectoryWriter,
    is_complete,
    read_trajectory,
    trajectory_path,
)

NUDGE = json.dumps(
    {
        "error": "no_tool_call",
        "hint": "Reply with a tool call. Call finish when the task is done, or escalate if it cannot be completed.",
    },
    sort_keys=True,
    separators=(",", ":"),
)


class ResumeError(Exception):
    """A resumable run directory contains trajectories from a different agent configuration."""


def _format_error_observation(action: Action) -> str:
    return json.dumps(
        {
            "error": "format_error",
            "kind": action.format_error,
            "hint": "Your last reply did not contain a valid structured tool call. Use the tool-calling interface.",
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def run_trial(
    env: Environment,
    agent: Agent,
    seed: int,
    *,
    trial: int = 0,
    trial_seed: int | None = None,
    budget: Budget | None = None,
    env_spec: str | None = None,
    recorder: TrajectoryWriter | None = None,
    clock: Callable[[], float] = time.monotonic,
    forced_termination: tuple[int, str] | None = None,
) -> TrialResult:
    """Run one agent on one task once.

    ``forced_termination=(turns, label)`` stops the episode after that many agent turns with the
    given label; replay uses it to reproduce time-budget terminations deterministically.
    """
    budget = budget or Budget(max_steps=env.default_max_steps)
    spec_name = env_spec or env.name
    if trial_seed is None:
        trial_seed = derive_seed(0, spec_name, seed, trial)
    task = env.task(seed)
    wall_start = clock()
    observation = env.reset(seed, trial)
    ctx = EpisodeContext(
        env=spec_name,
        task_seed=seed,
        trial=trial,
        trial_seed=trial_seed,
        tools=tuple(env.tools()),
        system_prompt=env.system_prompt(),
        max_steps=budget.max_steps,
    )
    agent.start(ctx)
    if recorder is not None:
        recorder.write(
            {
                "type": "header",
                "schema": SCHEMA_VERSION,
                "env": spec_name,
                "env_version": env.version,
                "task": task.to_dict(),
                "task_seed": seed,
                "trial": trial,
                "trial_seed": trial_seed,
                "agent": {"name": agent.name, "id": agent.agent_id(), "config": agent.config()},
                "budget": budget.to_dict(),
                "initial_observation": observation,
            }
        )

    tracker = BudgetTracker(budget, clock)
    terminated = "no_action"
    nudges = fmt_streak = fmt_total = misuse = steps = 0
    prompt_tokens = completion_tokens = 0
    agent_latency = 0.0

    def record(
        action: Action, obs: str, kind: str, done: bool = False, is_error: bool = False, bad: bool = False
    ) -> None:
        if recorder is not None:
            recorder.write(
                {
                    "type": "step",
                    "i": tracker.turns - 1,
                    "kind": kind,
                    "action": action.to_dict(),
                    "observation": obs,
                    "done": done,
                    "is_error": is_error,
                    "misuse": bad,
                }
            )

    while True:
        if forced_termination is not None and tracker.turns >= forced_termination[0]:
            terminated = forced_termination[1]
            break
        why = tracker.exceeded()
        if why:
            terminated = f"budget:{why}"
            break
        action = agent.act(observation)
        tracker.charge_turn(action.usage.total)
        prompt_tokens += action.usage.prompt_tokens
        completion_tokens += action.usage.completion_tokens
        agent_latency += action.latency_s
        why = tracker.exceeded(include_steps=False)
        if why:
            record(action, "", "dropped")
            terminated = f"budget:{why}"
            break
        if action.tool_call is None:
            if action.format_error:
                fmt_total += 1
                fmt_streak += 1
                observation = _format_error_observation(action)
                record(action, observation, "format_error", is_error=True)
                if fmt_streak >= budget.max_format_errors:
                    terminated = "format_error"
                    break
                continue
            fmt_streak = 0
            if nudges < budget.max_nudges:
                nudges += 1
                observation = NUDGE
                record(action, observation, "nudge", is_error=True)
                continue
            record(action, "", "no_action")
            terminated = "no_action"
            break
        fmt_streak = 0
        result = env.step(action.tool_call)
        steps += 1
        misuse += int(result.misuse)
        observation = result.observation
        record(action, observation, "tool", result.done, result.is_error, result.misuse)
        if result.done:
            terminated = action.tool_call.name if action.tool_call.name in ("finish", "escalate") else "done"
            break

    grade = env.grade()
    exceeded = terminated.startswith("budget:")
    passed = grade.passed and not exceeded
    reason = f"{terminated}; {grade.reason}" if exceeded else grade.reason
    digest = env.state_digest()
    result_obj = TrialResult(
        env=spec_name,
        task_seed=seed,
        tier=task.tier,
        expect=task.expect,
        kind=task.kind,
        trial=trial,
        trial_seed=trial_seed,
        agent=agent.name,
        passed=passed,
        outcome_ok=grade.outcome_ok and not exceeded,
        finished=grade.finished,
        escalated=grade.escalated,
        violations=list(grade.violations),
        reason=reason,
        terminated=terminated,
        steps=steps,
        misuse=misuse,
        format_errors=fmt_total,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        agent_latency_s=round(agent_latency, 6),
        wall_s=round(clock() - wall_start, 6),
        state_digest=digest,
        extra=env.extra_metrics(),
    )
    if recorder is not None:
        recorder.write(
            {
                "type": "end",
                "terminated": terminated,
                "grade": grade.to_dict(),
                "state_digest": digest,
                "result": result_obj.to_dict(),
            }
        )
        recorder.close()
    return result_obj


# ---------------------------------------------------------------------------------------- suites
EnvFactory = Callable[[], Environment]
AgentFactory = Callable[[], Agent]


def run_suite(
    make_env: EnvFactory,
    make_agent: AgentFactory,
    seeds: Iterable[int],
    n: int,
    *,
    env_spec: str,
    run_seed: int = 0,
    budget: Budget | None = None,
    run_dir: Path | None = None,
    resume: bool = True,
    on_trial: Callable[[TrialResult, bool], None] | None = None,
) -> list[TrialResult]:
    """Run ``n`` trials of every seed. With ``run_dir`` every trial is recorded; complete
    trajectories already present are loaded instead of re-run (``resume``), unless they were
    produced by a different agent configuration (:class:`ResumeError`)."""
    if n < 1:
        raise ValueError("n must be at least 1")
    agent = make_agent()
    env = make_env()
    results: list[TrialResult] = []
    for seed in seeds:
        for trial in range(n):
            trial_seed = derive_seed(run_seed, env_spec, seed, trial)
            path = trajectory_path(run_dir, env_spec, seed, trial) if run_dir is not None else None
            if path is not None and resume and path.exists() and is_complete(path):
                traj = read_trajectory(path)
                if traj.header["agent"]["id"] != agent.agent_id():
                    raise ResumeError(
                        f"{path} was produced by agent {traj.header['agent']['id']!r}, "
                        f"current agent is {agent.agent_id()!r}; use a fresh --run-dir"
                    )
                result = traj.result()
                if on_trial:
                    on_trial(result, True)
                results.append(result)
                continue
            writer = TrajectoryWriter(path) if path is not None else None
            try:
                result = run_trial(
                    env,
                    agent,
                    seed,
                    trial=trial,
                    trial_seed=trial_seed,
                    budget=budget,
                    env_spec=env_spec,
                    recorder=writer,
                )
            except BaseException:
                if writer is not None:
                    writer.abort()
                raise
            if on_trial:
                on_trial(result, False)
            results.append(result)
    agent.close()
    return results


# ----------------------------------------------------------------------------------------- replay
class ReplayAgent(Agent):
    """Feeds back the recorded actions in order. Once exhausted it ends the episode quietly."""

    name = "replay"

    def __init__(self, actions: list[Action]) -> None:
        self._actions = list(actions)
        self._i = 0

    def start(self, ctx: EpisodeContext) -> None:
        self._i = 0

    def act(self, observation: str) -> Action:
        if self._i >= len(self._actions):
            return Action()
        action = self._actions[self._i]
        self._i += 1
        return Action(
            tool_call=action.tool_call,
            message=action.message,
            usage=action.usage,
            latency_s=action.latency_s,
            format_error=action.format_error,
        )


@dataclass
class ReplayReport:
    ok: bool
    mismatches: list[str] = field(default_factory=list)
    original: TrialResult | None = None
    replayed: TrialResult | None = None


_COMPARED_STEP_KEYS = ("kind", "observation", "done", "is_error", "misuse")
_COMPARED_RESULT_KEYS = (
    "passed", "outcome_ok", "finished", "escalated", "violations", "reason", "terminated", "steps",
    "misuse", "format_errors", "prompt_tokens", "completion_tokens", "state_digest", "extra",
)  # fmt: skip


def replay_trajectory(path: Path, make_env: Callable[[str], Environment] | None = None) -> ReplayReport:
    """Replay a recorded trajectory in a fresh environment and compare everything deterministic.

    The recorded tool calls are fed back through the normal runner. Every observation, the
    termination reason, the final-state digest and the grade must equal the recording.
    """
    if make_env is None:
        from trialgauntlet.envs import make_env as default_make_env

        make_env = default_make_env
    traj: Trajectory = read_trajectory(path)
    header = traj.header
    env = make_env(header["env"])
    budget = Budget.from_dict(header["budget"])
    recorded_terminated = traj.end["terminated"]
    forced = None
    if recorded_terminated == "budget:time":
        forced = (len(traj.steps), recorded_terminated)
        budget = Budget.from_dict({**header["budget"], "max_seconds": None})
    original = traj.result()
    sink = MemoryRecorder()

    replayed = run_trial(
        env,
        ReplayAgent(traj.actions()),
        header["task_seed"],
        trial=header["trial"],
        trial_seed=header["trial_seed"],
        budget=budget,
        env_spec=header["env"],
        recorder=sink,
        forced_termination=forced,
    )
    mismatches: list[str] = []
    new_steps = [r for r in sink.records if r["type"] == "step"]
    if len(new_steps) != len(traj.steps):
        mismatches.append(f"step count: recorded {len(traj.steps)}, replayed {len(new_steps)}")
    for rec, new in zip(traj.steps, new_steps):
        for key in _COMPARED_STEP_KEYS:
            if rec.get(key) != new.get(key):
                mismatches.append(f"step {rec['i']} {key}: recorded {rec.get(key)!r}, replayed {new.get(key)!r}")
    for key in _COMPARED_RESULT_KEYS:
        a, b = getattr(original, key), getattr(replayed, key)
        if a != b:
            mismatches.append(f"result {key}: recorded {a!r}, replayed {b!r}")
    if traj.end["state_digest"] != replayed.state_digest:
        mismatches.append("end state_digest differs")
    return ReplayReport(ok=not mismatches, mismatches=mismatches, original=original, replayed=replayed)


__all__ = [
    "NUDGE",
    "ReplayAgent",
    "ReplayReport",
    "ResumeError",
    "TrajectoryError",
    "run_suite",
    "run_trial",
    "replay_trajectory",
]
