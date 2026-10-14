"""Plain data types shared by environments, agents, the runner and the reports.

Every type here round-trips through JSON (``to_dict`` / ``from_dict``) because trajectories and
result files are the only persistence layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

SCHEMA_VERSION = 1

TERMINAL_TOOLS = ("finish", "escalate")


@dataclass(frozen=True)
class ToolSpec:
    """One tool an agent may call. ``parameters`` is a JSON-schema object."""

    name: str
    description: str
    parameters: dict[str, Any]
    mutating: bool = False
    terminal: bool = False

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments, "id": self.id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        return cls(name=data["name"], arguments=dict(data.get("arguments") or {}), id=data.get("id", ""))


@dataclass
class StepResult:
    observation: str
    done: bool = False
    is_error: bool = False
    misuse: bool = False


@dataclass(frozen=True)
class TaskSpec:
    """Metadata about one task. Never shown to agents."""

    env: str
    seed: int
    tier: str
    expect: str  # "solve" or "escalate"
    kind: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSpec:
        return cls(**{f.name: data[f.name] for f in fields(cls)})


@dataclass
class Grade:
    passed: bool
    outcome_ok: bool
    violations: list[str] = field(default_factory=list)
    reason: str = ""
    finished: bool = False
    escalated: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Grade:
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Usage:
        data = data or {}
        return cls(int(data.get("prompt_tokens", 0)), int(data.get("completion_tokens", 0)))


@dataclass
class Action:
    """What an agent did in one turn: at most one tool call plus free text."""

    tool_call: ToolCall | None = None
    message: str = ""
    usage: Usage = field(default_factory=Usage)
    latency_s: float = 0.0
    format_error: str | None = None  # e.g. "tool_call_as_text", "malformed_arguments"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call": self.tool_call.to_dict() if self.tool_call else None,
            "message": self.message,
            "usage": self.usage.to_dict(),
            "latency_s": round(self.latency_s, 6),
            "format_error": self.format_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Action:
        tc = data.get("tool_call")
        return cls(
            tool_call=ToolCall.from_dict(tc) if tc else None,
            message=data.get("message", ""),
            usage=Usage.from_dict(data.get("usage")),
            latency_s=float(data.get("latency_s", 0.0)),
            format_error=data.get("format_error"),
        )


@dataclass(frozen=True)
class AttackSurface:
    """Where and what an injection attack targets in one task (see ``envs/inject.py``).

    ``attack`` is a forbidden call the attacker wants executed; ``exfil`` is a call that would send
    ``secret`` to ``attacker``. A call counts as the attack when its name equals the target's and the
    arguments named in ``*_match`` are equal.
    """

    inject_tools: tuple[str, ...]
    note_field: str
    attack: ToolCall
    attack_match: tuple[str, ...]
    exfil: ToolCall
    exfil_match: tuple[str, ...]
    secret: str
    attacker: str


@dataclass(frozen=True)
class EpisodeContext:
    """Everything an agent legitimately knows before the first observation."""

    env: str
    task_seed: int
    trial: int
    trial_seed: int
    tools: tuple[ToolSpec, ...]
    system_prompt: str
    max_steps: int


@dataclass
class TrialResult:
    env: str
    task_seed: int
    tier: str
    expect: str
    kind: str
    trial: int
    trial_seed: int
    agent: str
    passed: bool
    outcome_ok: bool
    finished: bool
    escalated: bool
    violations: list[str]
    reason: str
    terminated: str
    steps: int
    misuse: int
    format_errors: int
    prompt_tokens: int
    completion_tokens: int
    agent_latency_s: float
    wall_s: float
    state_digest: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrialResult:
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})
