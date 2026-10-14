"""Render result files into a markdown report and hand-written SVG charts.

Input is ``results/*.json`` only: nothing is recomputed and nothing is invented. With no result
file the report refuses to run (:class:`ReportError`) rather than render an empty or fabricated page.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from trialgauntlet.results import ResultsError, load_results

DEFAULT_THRESHOLD = 0.05
TRIVIAL_NAMES = ("no-op", "random-tool", "always-refuse")


class ReportError(Exception):
    """The report cannot be produced (no results, unreadable results)."""


Doc = dict[str, Any]


def collect(paths: Sequence[Path]) -> list[tuple[Path, Doc]]:
    """Load every ``*.json`` under the given files/directories (non-recursive for directories)."""
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files.extend(sorted(x for x in p.glob("*.json")))
        elif p.is_file():
            files.append(p)
        else:
            raise ReportError(f"no such file or directory: {p}")
    if not files:
        raise ReportError(
            "no result files (*.json) found; refusing to render a report with nothing in it. "
            "Run `trialgauntlet run ... --out results/<name>.json` or `trialgauntlet audit --out-dir results` first."
        )
    docs = []
    for f in files:
        try:
            docs.append((f, load_results(f)))
        except ResultsError as err:
            raise ReportError(str(err)) from err
    return docs


def classify(doc: Doc) -> str:
    """``real`` (LLM run against a real server), ``mock`` (plumbing test) or ``baseline``."""
    if doc["agent"]["type"] == "llm":
        return "mock" if doc["label"] == "MOCK" else "real"
    return "baseline"


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def _cell(metric: dict[str, Any]) -> str:
    ci = metric.get("ci")
    text = _pct(metric["value"])
    return f"{text} [{_pct(ci[0])}, {_pct(ci[1])}]" if ci else text


def md_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def base_of(spec: str) -> str:
    return spec.split("+", 1)[0]


def modifiers_of(spec: str) -> list[str]:
    return spec.split("+")[1:]


# --------------------------------------------------------------------------------------- tables
def llm_tables(doc: Doc) -> str:
    k = doc["run"]["k"]
    agent = doc["agent"]
    head = f"### {agent['name']}  (n={doc['run']['n']}, k={k}, temperature {agent.get('temperature', 'n/a')})"
    rows = []
    for spec, s in doc["environments"].items():
        m, r, u = s["metrics"], s["reliability"], s["usage"]
        rows.append(
            [
                spec,
                s["tasks"],
                _cell(m["pass@1"]),
                _cell(m["pass@k"]),
                _cell(m["pass^k"]),
                _pct(m["gap"]["value"]),
                _pct(m["outcome_only"]["value"]),
                f"{r['mean_policy_violations']:.2f}",
                f"{r['mean_tool_misuse']:.2f}",
                f"{u['mean_steps']:.1f}",
                f"{u['mean_prompt_tokens'] + u['mean_completion_tokens']:.0f}",
                "n/a" if u.get("mean_agent_latency_s") is None else f"{u['mean_agent_latency_s']:.2f}s",
                f"${u['cost_usd']:.4f}",
            ]
        )
    table = md_table(
        [
            "env", "tasks", "pass@1", f"pass@{k}", f"pass^{k}", "gap", "outcome-only", "violations/trial",
            "misuse/trial", "steps", "tokens/trial", "agent latency/trial", "cost",
        ],
        rows,
    )  # fmt: skip
    tier_rows = []
    for spec, s in doc["environments"].items():
        for tier, t in s["by_tier"].items():
            tier_rows.append([spec, tier, t["tasks"], _pct(t["pass@1"]), _pct(t["pass@k"]), _pct(t["pass^k"])])
        for expect, t in s["by_expect"].items():
            label = "unsolvable subset (must escalate)" if expect == "escalate" else "solvable"
            tier_rows.append([spec, label, t["tasks"], _pct(t["pass@1"]), _pct(t["pass@k"]), _pct(t["pass^k"])])
    tiers = md_table(["env", "slice", "tasks", "pass@1", f"pass@{k}", f"pass^{k}"], tier_rows)
    return f"{head}\n\n{table}\n\nBy slice:\n\n{tiers}"


def baseline_table(docs: Sequence[Doc]) -> str:
    rows = []
    for doc in docs:
        k = doc["run"]["k"]
        for spec, s in doc["environments"].items():
            if modifiers_of(spec):
                continue
            m = s["metrics"]
            rows.append(
                [
                    doc["agent"]["name"],
                    spec,
                    s["tasks"],
                    _cell(m["pass@1"]),
                    _pct(m["pass@k"]["value"]),
                    _pct(m["pass^k"]["value"]),
                    _pct(m["outcome_only"]["value"]),
                    f"{s['reliability']['mean_policy_violations']:.2f}",
                ]
            )
    k = docs[0]["run"]["k"] if docs else 4
    return md_table(
        ["agent", "env", "tasks", "pass@1", f"pass@{k}", f"pass^{k}", "outcome-only", "violations/trial"], rows
    )


def audit_rows(docs: Sequence[Doc], threshold: float | None = None) -> list[dict[str, Any]]:
    """Rows of the degenerate-success table: trivial baselines on every environment spec."""
    rows = []
    for doc in docs:
        if doc["agent"]["name"] not in TRIVIAL_NAMES:
            continue
        thr = threshold if threshold is not None else doc["run"].get("threshold", DEFAULT_THRESHOLD)
        for spec, s in doc["environments"].items():
            if set(modifiers_of(spec)) - {"naive"}:
                continue
            value = s["metrics"]["pass@1"]["value"]
            rows.append(
                {
                    "env": spec,
                    "agent": doc["agent"]["name"],
                    "value": value,
                    "ci": s["metrics"]["pass@1"].get("ci"),
                    "threshold": thr,
                    "flag": value > thr,
                    "demo": "naive" in modifiers_of(spec),
                }
            )
    order = {n: i for i, n in enumerate(TRIVIAL_NAMES)}
    rows.sort(key=lambda r: (r["demo"], base_of(r["env"]), order.get(r["agent"], 9)))
    return rows


def audit_table(rows: Sequence[dict[str, Any]]) -> str:
    body = [
        [
            r["env"],
            r["agent"],
            _pct(r["value"]),
            "n/a" if not r["ci"] else f"{_pct(r['ci'][0])}-{_pct(r['ci'][1])}",
            _pct(r["threshold"]),
            "FLAG" if r["flag"] else "ok",
            "demo (naive grader)" if r["demo"] else "gated",
        ]
        for r in rows
    ]
    return md_table(["env", "trivial baseline", "pass@1", "95% CI", "threshold", "verdict", "role"], body)


def suites_markdown(docs: Sequence[Doc]) -> str:
    inj_rows, flt_rows = [], []
    for doc in docs:
        for spec, s in doc["environments"].items():
            extra = s.get("extra", {})
            if "injection" in extra:
                i = extra["injection"]
                inj_rows.append(
                    [
                        doc["agent"]["name"],
                        spec,
                        _pct(i["attack_success_rate"]),
                        _pct(i["exposed_rate"]),
                        _pct(i["attack_success_rate_given_exposed"]),
                        _pct(i["utility_under_attack"]),
                    ]
                )
            if "faults" in extra:
                f = extra["faults"]
                flt_rows.append(
                    [
                        doc["agent"]["name"],
                        spec,
                        _pct(s["metrics"]["pass@1"]["value"]),
                        _pct(s["metrics"]["pass^k"]["value"]),
                        f"{f['mean_faults_injected']:.2f}",
                        _pct(f["pass_rate_given_fault"]),
                        _pct(f["pass_rate_no_fault"]),
                    ]
                )
    out = []
    if inj_rows:
        out.append("## Injection suite\n")
        out.append(
            md_table(
                ["agent", "env", "attack success", "exposed", "success when exposed", "utility under attack"], inj_rows
            )
        )
        out.append(
            "\nAttack success is judged on tool calls. Exposure is the share of trials that read a poisoned result."
        )
    if flt_rows:
        out.append("\n## Fault suite\n")
        out.append(
            md_table(
                ["agent", "env", "pass@1", "pass^k", "faults/trial", "pass rate when a fault hit", "pass rate without"],
                flt_rows,
            )
        )
    return "\n".join(out)


def render_markdown(entries: Sequence[tuple[Path, Doc]], threshold: float | None = None) -> str:
    docs = [d for _, d in entries]
    real = [d for d in docs if classify(d) == "real"]
    mock = [d for d in docs if classify(d) == "mock"]
    base = [d for d in docs if classify(d) == "baseline"]
    out = ["# trialgauntlet report", ""]
    out.append(
        f"Generated from {len(entries)} result file(s): "
        + ", ".join(f"`{p.name}` ({classify(d)})" for p, d in entries)
        + ".\n"
    )
    out.append("## LLM results\n")
    if real:
        for d in real:
            out.append(llm_tables(d) + "\n")
    else:
        out.append(
            "**LLM results: NOT YET RUN.** No result file from a real model server is present. "
            "Numbers elsewhere in this report come from the built-in non-LLM baseline agents.\n"
        )
    if mock:
        out.append("## MOCK runs (plumbing only)\n")
        out.append(
            "> **MOCK.** These runs used the built-in mock server (scripted replies, no model). They exist to test the "
            "adapter and the reporting path. They say nothing about any model.\n"
        )
        for d in mock:
            out.append(llm_tables(d) + "\n")
    if base:
        out.append("## Baseline agents (non-LLM, deterministic)\n")
        out.append(baseline_table(base) + "\n")
        rows = audit_rows(base, threshold)
        if rows:
            out.append("## Degenerate-success audit\n")
            out.append(audit_table(rows))
            flagged = [r for r in rows if r["flag"] and not r["demo"]]
            out.append(
                "\n"
                + (
                    f"AUDIT PASSED: no trivial baseline exceeds {_pct(rows[0]['threshold'])} on a gated environment."
                    if not flagged
                    else f"AUDIT FAILED: {len(flagged)} gated flag(s): "
                    + ", ".join(f"{r['env']}/{r['agent']}" for r in flagged)
                )
                + "\n"
            )
    suites = suites_markdown(docs)
    if suites:
        out.append(suites + "\n")
    out.append("Definitions: `docs/METHODOLOGY.md`. Threats to validity: `docs/THREATS_TO_VALIDITY.md`.")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------------ SVG
STYLE = """<style>
:root{--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;--s1:#2a78d6;--s2:#eb6834;--crit:#d03b3b}
@media (prefers-color-scheme: dark){:root{--ink:#f0efec;--ink2:#c3c2b7;--grid:#3a3a36;--s1:#3987e5;--s2:#d95926;--crit:#d03b3b}}
text{fill:var(--ink);font:12px system-ui,-apple-system,Segoe UI,sans-serif}
.sub{fill:var(--ink2);font-size:11px}.ttl{font-size:15px;font-weight:600}.grid{stroke:var(--grid);stroke-width:1}
.axis{stroke:var(--ink2);stroke-width:1}.thr{stroke:var(--ink);stroke-width:1.5}
.b1{fill:var(--s1)}.b2{fill:var(--s2)}.bc{fill:var(--crit)}
</style>"""


def _svg(width: int, height: int, title: str, desc: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="t d">\n<title id="t">{escape(title)}</title>\n<desc id="d">{escape(desc)}</desc>\n'
        f"{STYLE}\n{body}\n</svg>\n"
    )


def _bar(x: float, y: float, w: float, h: float, cls: str, tip: str) -> str:
    """A bar with a square baseline end and a 4px rounded data end (a bare rect when too short)."""
    if w < 1:
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="1" height="{h}" class="{cls}"><title>{escape(tip)}</title></rect>'
    r = min(4.0, w, h / 2)
    path = f"M{x:.1f},{y:.1f}H{x + w - r:.1f}a{r},{r} 0 0 1 {r},{r}V{y + h - r:.1f}a{r},{r} 0 0 1 -{r},{r}H{x:.1f}Z"
    return f'<path d="{path}" class="{cls}"><title>{escape(tip)}</title></path>'


def _trim(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def gap_rows(docs: Sequence[Doc]) -> list[dict[str, Any]]:
    """Rows for the pass@1 versus pass^k chart: every LLM run, every row with a visible gap, and the oracle."""
    rows = []
    for doc in docs:
        kind = classify(doc)
        for spec, s in doc["environments"].items():
            mods = modifiers_of(spec)
            if "naive" in mods or any(m.startswith("inject") for m in mods):
                continue
            m = s["metrics"]
            p1, ph = m["pass@1"]["value"], m["pass^k"]["value"]
            keep = kind != "baseline" or p1 - ph > 0.005 or (doc["agent"]["name"] == "scripted-oracle" and not mods)
            if keep:
                prefix = "[MOCK] " if kind == "mock" else ""
                rows.append({"label": f"{prefix}{doc['agent']['name']}", "env": spec, "p1": p1, "ph": ph, "k": s["k"]})
    return rows


def svg_gap_chart(docs: Sequence[Doc]) -> str:
    rows = gap_rows(docs)
    k = rows[0]["k"] if rows else 4
    left, bar_w, row_h = 250, 400, 40
    width, top = left + bar_w + 150, 74
    height = top + max(1, len(rows)) * row_h + 34
    body = [
        f'<text x="16" y="24" class="ttl">pass@1 versus pass^{k}, per environment</text>',
        '<text x="16" y="42" class="sub">The gap between the two bars is the inconsistency that pass@1 alone hides.</text>',
        '<rect x="16" y="52" width="10" height="10" class="b1"/><text x="32" y="61" class="sub">pass@1</text>',
        f'<rect x="92" y="52" width="10" height="10" class="b2"/><text x="108" y="61" class="sub">pass^{k}</text>',
    ]
    for pct in (0, 25, 50, 75, 100):
        x = left + bar_w * pct / 100
        body.append(f'<line x1="{x}" y1="{top - 6}" x2="{x}" y2="{top + len(rows) * row_h}" class="grid"/>')
        body.append(f'<text x="{x}" y="{top + len(rows) * row_h + 16}" text-anchor="middle" class="sub">{pct}%</text>')
    if not rows:
        body.append(f'<text x="{left}" y="{top + 24}" class="sub">no rows to plot</text>')
    for i, r in enumerate(rows):
        y = top + i * row_h
        body.append(f'<text x="{left - 10}" y="{y + 14}" text-anchor="end">{escape(_trim(r["label"], 28))}</text>')
        body.append(
            f'<text x="{left - 10}" y="{y + 28}" text-anchor="end" class="sub">{escape(_trim(r["env"], 30))}</text>'
        )
        w1, wk = bar_w * r["p1"], bar_w * r["ph"]
        body.append(_bar(left, y + 4, w1, 14, "b1", f"{r['label']} {r['env']}: pass@1 {_pct(r['p1'])}"))
        body.append(_bar(left, y + 20, wk, 14, "b2", f"{r['label']} {r['env']}: pass^{r['k']} {_pct(r['ph'])}"))
        body.append(f'<text x="{left + w1 + 6:.1f}" y="{y + 15}" class="sub">{_pct(r["p1"])}</text>')
        body.append(f'<text x="{left + wk + 6:.1f}" y="{y + 31}" class="sub">{_pct(r["ph"])}</text>')
        body.append(
            f'<text x="{left + bar_w + 66}" y="{y + 24}" class="sub">gap {100 * (r["p1"] - r["ph"]):.1f} pts</text>'
        )
    body.append(f'<line x1="{left}" y1="{top - 6}" x2="{left}" y2="{top + len(rows) * row_h}" class="axis"/>')
    return _svg(
        width, height, f"pass@1 versus pass^{k}",
        "Horizontal bars per agent and environment comparing pass@1 with pass^k.", "\n".join(body),
    )  # fmt: skip


def svg_audit_chart(docs: Sequence[Doc], threshold: float | None = None) -> str:
    rows = audit_rows(docs, threshold)
    thr = rows[0]["threshold"] if rows else DEFAULT_THRESHOLD
    top_max = max([0.1, *[r["value"] for r in rows]])
    top_max = min(1.0, max(0.1, round(top_max * 1.15 + 0.04, 2)))
    left, bar_w, row_h = 230, 420, 24
    gated = [r for r in rows if not r["demo"]]
    demo = [r for r in rows if r["demo"]]
    width, top = left + bar_w + 130, 96
    extra = 26 if demo else 0
    height = top + (len(gated) + len(demo)) * row_h + extra + 40
    body = [
        '<text x="16" y="24" class="ttl">Degenerate-success audit: trivial baselines (pass@1)</text>',
        f'<text x="16" y="42" class="sub">A trivial baseline above the {_pct(thr, 0)} line is flagged. Lower is better here.</text>',
        '<rect x="16" y="52" width="10" height="10" class="b1"/><text x="32" y="61" class="sub">within threshold</text>',
        '<rect x="140" y="52" width="10" height="10" class="bc"/><text x="156" y="61" class="sub">FLAG: above threshold</text>',
    ]
    plot_bottom = top + (len(gated) + len(demo)) * row_h + extra
    for tick in range(0, int(round(top_max * 100)) + 1, 10 if top_max > 0.25 else 5):
        x = left + bar_w * (tick / 100) / top_max
        body.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{plot_bottom}" class="grid"/>')
        body.append(f'<text x="{x:.1f}" y="{plot_bottom + 16}" text-anchor="middle" class="sub">{tick}%</text>')
    thr_x = left + bar_w * thr / top_max
    body.append(f'<line x1="{thr_x:.1f}" y1="{top - 10}" x2="{thr_x:.1f}" y2="{plot_bottom}" class="thr"/>')
    body.append(f'<text x="{thr_x + 5:.1f}" y="{top - 12}" class="sub">threshold {_pct(thr, 0)}</text>')
    y = top
    for group, title in ((gated, None), (demo, "Demonstration: naive grader (not gated)")):
        if not group:
            continue
        if title:
            body.append(f'<text x="16" y="{y + 16}" class="sub">{escape(title)}</text>')
            y += extra
        for r in group:
            cls = "bc" if r["flag"] else "b1"
            label = f"{r['env']} · {r['agent']}"
            body.append(f'<text x="{left - 10}" y="{y + 15}" text-anchor="end">{escape(_trim(label, 34))}</text>')
            w = bar_w * r["value"] / top_max
            tip = f"{r['env']} {r['agent']}: pass@1 {_pct(r['value'])} (threshold {_pct(thr, 0)})"
            body.append(_bar(left, y + 4, w, 14, cls, tip))
            tag = f"{_pct(r['value'])}" + ("  FLAG" if r["flag"] else "")
            body.append(f'<text x="{left + w + 6:.1f}" y="{y + 15}" class="sub">{tag}</text>')
            y += row_h
    body.append(f'<line x1="{left}" y1="{top - 6}" x2="{left}" y2="{plot_bottom}" class="axis"/>')
    return _svg(
        width, height, "Degenerate-success audit",
        "Pass@1 of the no-op, random and always-refuse baselines per environment against the audit threshold.", "\n".join(body),
    )  # fmt: skip


def write_report(
    entries: Sequence[tuple[Path, Doc]], out_dir: Path, threshold: float = DEFAULT_THRESHOLD
) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = [d for _, d in entries]
    files = {
        "report.md": render_markdown(entries, threshold),
        "pass1_vs_passk.svg": svg_gap_chart(docs),
        "audit.svg": svg_audit_chart(docs, threshold),
    }
    paths = []
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths
