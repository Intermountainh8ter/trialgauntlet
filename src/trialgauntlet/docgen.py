"""Generate the numeric tables embedded in the README from real runs.

The README contains blocks delimited by ``<!-- NAME:BEGIN -->`` and ``<!-- NAME:END -->``. This
module recomputes them (the audit is re-run; suite tables are read from ``results/*.json``) so the
numbers in the documentation can never drift from the code. ``--check`` is what CI and the test
suite use.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from trialgauntlet.audit import AuditReport, format_table, run_audit
from trialgauntlet.results import load_results

ROOT = Path(__file__).resolve().parents[2]
ENVS = ("fleet", "ledger", "config")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def audit_report() -> AuditReport:
    report = run_audit(list(ENVS))
    run_audit([f"{e}+naive" for e in ENVS], gated=False, report=report)
    return report


def audit_block(report: AuditReport) -> str:
    return format_table(report, markdown=True, rows=[r for r in report.rows if r.gated])


def demo_block(report: AuditReport) -> str:
    return format_table(report, markdown=True, rows=[r for r in report.rows if not r.gated])


def injection_block(results_dir: Path) -> str:
    rows = [
        "| environment | variant | agent | attack success | exposed | utility under attack |",
        "|---|---|---|---|---|---|",
    ]
    for agent in ("oracle", "gullible"):
        doc = load_results(results_dir / f"suite-injection-{agent}.json")
        for spec, summary in doc["environments"].items():
            inj = summary["extra"]["injection"]
            env = spec.split("+")[0]
            rows.append(
                f"| {env} | {inj['variant']} | {doc['agent']['name']} | {_pct(inj['attack_success_rate'])} "
                f"| {_pct(inj['exposed_rate'])} | {_pct(inj['utility_under_attack'])} |"
            )
    return "\n".join(rows)


def faults_block(results_dir: Path) -> str:
    rows = [
        "| environment | agent | pass@1 | pass^4 | faults per trial | pass rate when a fault hit |",
        "|---|---|---|---|---|---|",
    ]
    for spec in ("fleet", "ledger", "config"):
        for agent in ("oracle", "oracle-retry"):
            doc = load_results(results_dir / f"suite-faults-{agent}.json")
            summary = doc["environments"][f"{spec}+fault=mixed:0.3"]
            m, flt = summary["metrics"], summary["extra"]["faults"]
            rows.append(
                f"| {spec} | {doc['agent']['name']} | {_pct(m['pass@1']['value'])} | {_pct(m['pass^k']['value'])} "
                f"| {flt['mean_faults_injected']:.2f} | {_pct(flt['pass_rate_given_fault'])} |"
            )
    return "\n".join(rows)


def render_blocks(results_dir: Path | None = None) -> dict[str, str]:
    results_dir = results_dir or ROOT / "results"
    report = audit_report()
    return {
        "AUDIT": audit_block(report),
        "DEMO": demo_block(report),
        "INJECTION": injection_block(results_dir),
        "FAULTS": faults_block(results_dir),
    }


BLOCK_RE = re.compile(r"(<!-- (?P<name>[A-Z_]+):BEGIN -->\n)(?P<body>.*?)(\n<!-- (?P=name):END -->)", re.S)


def update_text(text: str, blocks: dict[str, str]) -> str:
    def sub(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in blocks:
            return match.group(0)
        return f"{match.group(1)}{blocks[name]}{match.group(4)}"

    return BLOCK_RE.sub(sub, text)


def main(argv: Sequence[str] | None = None, compute: Callable[[], dict[str, str]] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m trialgauntlet.docgen", description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, default=[ROOT / "README.md", ROOT / "docs" / "SUITES.md"])
    parser.add_argument("--check", action="store_true", help="exit 1 if the tables are stale")
    args = parser.parse_args(argv)
    blocks = (compute or render_blocks)()
    stale = 0
    for path in args.files:
        text = path.read_text(encoding="utf-8")
        new = update_text(text, blocks)
        if new == text:
            print(f"{path.name}: tables are up to date")
        elif args.check:
            print(f"{path.name}: tables are stale; run: python -m trialgauntlet.docgen", file=sys.stderr)
            stale += 1
        else:
            path.write_text(new, encoding="utf-8")
            print(f"{path.name}: tables updated")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
