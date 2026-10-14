"""The degenerate-success audit.

Runs the baseline agents on every environment and flags any environment where

* a trivial baseline (no-op, random-tool, always-refuse) scores above the threshold,
* the scripted oracle does not solve every task (the environment may be unsolvable or the grader
  too strict), or
* the greedy-unsafe baseline passes (the policy grader failed to catch a shortcut).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from trialgauntlet.agents.registry import BASELINES, DISPLAY, TRIVIAL, make_baseline
from trialgauntlet.budget import Budget
from trialgauntlet.harness import evaluate_env

DEFAULT_THRESHOLD = 0.05
METRICS = ("pass@1", "pass@k", "pass^k")


@dataclass
class AuditRow:
    env: str
    agent_key: str
    agent: str
    pass1: float
    passk: float
    pass_hat: float
    outcome_only: float
    flagged: bool
    verdict: str
    gated: bool = True
    ci_low: float = 0.0
    ci_high: float = 0.0


@dataclass
class AuditReport:
    n: int
    k: int
    threshold: float
    metric: str
    seed: int
    rows: list[AuditRow] = field(default_factory=list)
    summaries: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    @property
    def flags(self) -> list[AuditRow]:
        return [r for r in self.rows if r.flagged and r.gated]

    @property
    def ok(self) -> bool:
        return not self.flags

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "k": self.k,
            "threshold": self.threshold,
            "metric": self.metric,
            "seed": self.seed,
            "ok": self.ok,
            "rows": [r.__dict__ for r in self.rows],
        }


def judge(agent_key: str, value: dict[str, float], threshold: float, metric: str) -> tuple[bool, str]:
    """Verdict for one (agent, environment) cell. ``value`` maps metric name to its mean."""
    if agent_key in TRIVIAL:
        if value[metric] > threshold:
            return True, f"FLAG: trivial baseline exceeds {threshold:.1%}"
        return False, "ok"
    if agent_key == "oracle":
        if value["pass@1"] < 1.0 - 1e-9:
            return True, f"FLAG: oracle solves only {value['pass@1']:.1%}"
        return False, "ok: solvable"
    if agent_key == "greedy":
        if value[metric] > threshold:
            return True, "FLAG: policy grader accepted a shortcut"
        return False, "ok: shortcut caught"
    return False, "ok"


def run_audit(
    envs: Sequence[str],
    *,
    agents: Sequence[str] = BASELINES,
    n: int = 8,
    k: int = 4,
    threshold: float = DEFAULT_THRESHOLD,
    metric: str = "pass@1",
    seed: int = 0,
    n_boot: int = 1000,
    budget: Budget | None = None,
    gated: bool = True,
    report: AuditReport | None = None,
) -> AuditReport:
    """Audit ``envs`` (environment specs). Pass ``report`` to append to an existing one."""
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}")
    if k > n:
        raise ValueError(f"k={k} must not exceed n={n}")
    report = report or AuditReport(n=n, k=k, threshold=threshold, metric=metric, seed=seed)
    for spec in envs:
        base = spec.split("+", 1)[0]
        for agent_key in agents:
            _, summary = evaluate_env(
                spec,
                make_baseline(agent_key, base),
                n=n,
                k=k,
                seed=seed,
                budget=budget,
                n_boot=n_boot,
                include_timing=False,
            )
            report.summaries.setdefault(agent_key, {})[spec] = summary
            m = summary["metrics"]
            value = {name: m[name]["value"] for name in METRICS}
            flagged, verdict = judge(agent_key, value, threshold, metric)
            report.rows.append(
                AuditRow(
                    env=spec,
                    agent_key=agent_key,
                    agent=DISPLAY[agent_key],
                    pass1=value["pass@1"],
                    passk=value["pass@k"],
                    pass_hat=value["pass^k"],
                    outcome_only=m["outcome_only"]["value"],
                    flagged=flagged,
                    verdict=verdict,
                    gated=gated,
                    ci_low=m["pass@1"]["ci"][0],
                    ci_high=m["pass@1"]["ci"][1],
                )
            )
    return report


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def format_table(report: AuditReport, markdown: bool = False, rows: Sequence[AuditRow] | None = None) -> str:
    k = report.k
    rows = report.rows if rows is None else rows
    head = ["env", "agent", "pass@1", "95% CI", f"pass@{k}", f"pass^{k}", "outcome-only", "verdict"]
    body = [
        [
            r.env,
            r.agent,
            _pct(r.pass1),
            f"{100 * r.ci_low:.1f}-{100 * r.ci_high:.1f}%",
            _pct(r.passk),
            _pct(r.pass_hat),
            _pct(r.outcome_only),
            r.verdict,
        ]
        for r in rows
    ]
    if markdown:
        lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        return "\n".join(lines)
    widths = (
        [max(len(head[i]), *(len(row[i]) for row in body)) for i in range(len(head))]
        if body
        else [len(h) for h in head]
    )
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [fmt.format(*head), fmt.format(*("-" * w for w in widths))]
    out += [fmt.format(*row) for row in body]
    return "\n".join(out)


def format_summary(report: AuditReport) -> str:
    gated = [r for r in report.rows if r.gated]
    if report.ok:
        return (
            f"AUDIT PASSED: no trivial baseline exceeds {report.threshold:.1%} ({report.metric}), the oracle solves "
            f"every task and the greedy-unsafe shortcut is caught, on {len({r.env for r in gated})} environment(s)."
        )
    lines = [f"AUDIT FAILED: {len(report.flags)} flag(s)"]
    lines += [f"  - {r.env} / {r.agent}: {r.verdict}" for r in report.flags]
    return "\n".join(lines)
