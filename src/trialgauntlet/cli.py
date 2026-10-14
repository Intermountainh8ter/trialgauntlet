"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from trialgauntlet import __version__

BUILTIN_ENVS = ("fleet", "ledger", "config")


class CLIError(Exception):
    """A user-facing error: printed without a traceback, exit status 2."""


Configure = Callable[[argparse.ArgumentParser], None]
Handler = Callable[[argparse.Namespace], int]
COMMANDS: dict[str, tuple[str, Configure, Handler]] = {}


def command(name: str, help_text: str, configure: Configure) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        COMMANDS[name] = (help_text, configure, fn)
        return fn

    return deco


def resolve_envs(arg: str) -> list[str]:
    """``all`` or a comma separated list of environment specs (``fleet,ledger+naive``)."""
    from trialgauntlet.envs import make_env

    names = list(BUILTIN_ENVS) if arg == "all" else [x.strip() for x in arg.split(",") if x.strip()]
    if not names:
        raise CLIError("no environments given")
    for spec in names:
        try:
            make_env(spec)
        except (KeyError, ValueError) as err:
            raise CLIError(str(err.args[0] if err.args else err)) from err
    return names


def _csv(value: str | None) -> list[str] | None:
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


def _pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


# ------------------------------------------------------------------------------------- list
def _cfg_list(p: argparse.ArgumentParser) -> None:
    p.add_argument("--env", default="all", help="'all' or comma separated environment specs")


@command("list", "list environments, task counts, tiers and scenario kinds", _cfg_list)
def cmd_list(args: argparse.Namespace) -> int:
    from trialgauntlet.envs import make_env

    for spec in resolve_envs(args.env):
        env = make_env(spec)
        tasks = env.task_specs()
        tiers = {t: sum(1 for x in tasks if x.tier == t) for t in sorted({x.tier for x in tasks})}
        esc = sum(1 for x in tasks if x.expect == "escalate")
        print(f"{spec}: {len(tasks)} tasks, tiers {tiers}, {esc} unsolvable/ambiguous (expect escalate)")
        seen: dict[str, tuple[str, str]] = {}
        for t in tasks:
            seen.setdefault(t.kind, (t.tier, t.expect))
        for kind, (tier, expect) in seen.items():
            print(f"    {kind:<22} {tier}  {expect}")
    return 0


# -------------------------------------------------------------------------------------- run
def _cfg_run(p: argparse.ArgumentParser) -> None:
    from trialgauntlet.agents.registry import ALL_AGENTS

    p.add_argument("--agent", default="oracle", help=f"one of {', '.join(ALL_AGENTS)}")
    p.add_argument("--env", default="all", help="'all' or comma separated environment specs, e.g. fleet,ledger+naive")
    p.add_argument("--n", type=int, default=8, help="trials per task")
    p.add_argument("--k", type=int, default=4, help="k for pass@k and pass^k (must be <= n)")
    p.add_argument("--seed", type=int, default=0, help="run seed (trial seeds are derived from it)")
    p.add_argument(
        "--inject", help="wrap every environment in an injection variant: instruction, fake_system, exfil or all"
    )
    p.add_argument(
        "--fault", help="wrap every environment in a fault profile, e.g. transient, mixed:0.3 (see docs/SUITES.md)"
    )
    p.add_argument("--tiers", help="comma separated tiers to run, e.g. T1,T2")
    p.add_argument("--kinds", help="comma separated scenario kinds to run")
    p.add_argument("--limit", type=int, help="run only the first N matching tasks per environment")
    p.add_argument("--max-steps", type=int, help="agent turns per trial (default: per environment)")
    p.add_argument("--run-dir", type=Path, help="record trajectories here; makes the run resumable")
    p.add_argument("--no-resume", action="store_true", help="re-run trials even if trajectories exist")
    p.add_argument("--out", type=Path, help="write the results JSON here")
    p.add_argument("--n-boot", type=int, default=1000, help="bootstrap resamples for confidence intervals")


def expand_specs(envs: list[str], inject: str | None, fault: str | None) -> list[str]:
    """Apply ``--inject`` / ``--fault`` to environment specs (``--inject all`` expands to every variant)."""
    from trialgauntlet.envs.inject import VARIANTS

    if inject is not None and inject != "all" and inject not in VARIANTS:
        raise CLIError(f"unknown injection variant '{inject}'. known: {', '.join(VARIANTS)}, all")
    variants: list[str | None] = list(VARIANTS) if inject == "all" else [inject]
    return [
        env + (f"+inject={v}" if v else "") + (f"+fault={fault}" if fault else "") for env in envs for v in variants
    ]


def print_env_summary(spec: str, s: dict) -> None:
    m = s["metrics"]
    k = s["k"]

    def cell(name: str) -> str:
        c = m[name]
        ci = c.get("ci")
        return f"{_pct(c['value'])}" + (f" [{_pct(ci[0]).strip()}, {_pct(ci[1]).strip()}]" if ci else "")

    print(f"{spec}: {s['tasks']} tasks x n={s['n']} trials")
    print(f"    pass@1     {cell('pass@1')}")
    print(f"    pass@{k:<5} {cell('pass@k')}")
    print(f"    pass^{k:<5} {cell('pass^k')}")
    print(f"    gap        {_pct(m['gap']['value'])}  (pass@1 - pass^{k})")
    print(f"    outcome-only (ignoring policy violations)  {_pct(m['outcome_only']['value'])}")
    r = s["reliability"]
    print(
        f"    violations/trial {r['mean_policy_violations']:.2f} (rate {_pct(r['violation_rate']).strip()}), "
        f"tool misuse/trial {r['mean_tool_misuse']:.2f}, steps/trial {s['usage']['mean_steps']:.1f}"
    )
    print(f"    terminated: {s['terminated']}")
    inj = s.get("extra", {}).get("injection")
    if inj:
        given = inj["attack_success_rate_given_exposed"]
        print(
            f"    injection ({inj['variant']}): attack success {_pct(inj['attack_success_rate']).strip()} "
            f"(exposed in {_pct(inj['exposed_rate']).strip()} of trials, "
            f"{'n/a' if given is None else _pct(given).strip()} when exposed), "
            f"utility under attack {_pct(inj['utility_under_attack']).strip()}"
        )
    flt = s.get("extra", {}).get("faults")
    if flt:
        rec = flt["pass_rate_given_fault"]
        retries = flt["mean_retries_after_fault"]
        print(
            f"    faults: {flt['mean_faults_injected']:.2f}/trial, {flt['trials_with_fault']} trials hit, "
            f"pass rate when hit {'n/a' if rec is None else _pct(rec).strip()}, "
            f"retries after a fault {'n/a' if retries is None else retries}"
        )


@command("run", "run an agent on environments and print/write pass@1, pass@k, pass^k", _cfg_run)
def cmd_run(args: argparse.Namespace) -> int:
    from trialgauntlet.agents.registry import ALL_AGENTS, DISPLAY, EXTRA, make_baseline
    from trialgauntlet.budget import Budget
    from trialgauntlet.envs import make_env
    from trialgauntlet.harness import evaluate_env, select_seeds
    from trialgauntlet.results import build_results, write_results

    if args.agent not in ALL_AGENTS:
        raise CLIError(f"unknown agent '{args.agent}'. known: {', '.join(ALL_AGENTS)}")
    if args.k > args.n:
        raise CLIError(f"--k ({args.k}) must not exceed --n ({args.n}): pass^k needs at least k trials per task")
    envs = expand_specs(resolve_envs(args.env), args.inject, args.fault)
    envs = resolve_envs(",".join(envs))
    summaries = {}
    agent_info: dict = {}
    for spec in envs:
        base = spec.split("+", 1)[0]
        factory = make_baseline(args.agent, base)
        env = make_env(spec)
        try:
            seeds = select_seeds(spec, tiers=_csv(args.tiers), kinds=_csv(args.kinds), limit=args.limit)
        except ValueError as err:
            raise CLIError(str(err)) from err
        budget = Budget(max_steps=args.max_steps or env.default_max_steps)
        agent = factory()
        agent_info = {
            "name": DISPLAY.get(args.agent) or EXTRA[args.agent],
            "id": agent.agent_id(),
            "type": "baseline",
            "config": agent.config(),
        }
        _, summary = evaluate_env(
            spec,
            factory,
            n=args.n,
            k=args.k,
            seed=args.seed,
            seeds=seeds,
            budget=budget,
            run_dir=args.run_dir,
            resume=not args.no_resume,
            n_boot=args.n_boot,
            include_timing=False,
        )
        summaries[spec] = summary
        print_env_summary(spec, summary)
    if args.out:
        doc = build_results(
            agent=agent_info,
            label="BASELINE",
            summaries=summaries,
            run={"n": args.n, "k": args.k, "seed": args.seed, "n_boot": args.n_boot},
        )
        write_results(args.out, doc)
        print(f"wrote {args.out}")
    return 0


# ------------------------------------------------------------------------------------ audit
def _cfg_audit(p: argparse.ArgumentParser) -> None:
    p.add_argument("--env", default="all", help="'all' or comma separated environment specs")
    p.add_argument("--n", type=int, default=8, help="trials per task")
    p.add_argument("--k", type=int, default=4, help="k for pass@k and pass^k")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--threshold", type=float, default=0.05, help="FLAG when a trivial baseline exceeds this (0-1)")
    p.add_argument(
        "--metric", default="pass@1", choices=["pass@1", "pass@k", "pass^k"], help="metric compared to the threshold"
    )
    p.add_argument("--agents", help="comma separated subset of noop,random,refuse,oracle,greedy")
    p.add_argument("--format", choices=["table", "markdown", "json"], default="table")
    p.add_argument("--no-demo", action="store_true", help="skip the naive-grader demonstration rows")
    p.add_argument("--out-dir", type=Path, help="write results/baseline-<agent>.json files here")
    p.add_argument("--no-fail", action="store_true", help="exit 0 even when the audit raises flags")
    p.add_argument("--n-boot", type=int, default=1000)


@command("audit", "run the degenerate-success audit: trivial baselines must not score", _cfg_audit)
def cmd_audit(args: argparse.Namespace) -> int:
    from trialgauntlet.agents.registry import BASELINES, DISPLAY
    from trialgauntlet.audit import format_summary, format_table, run_audit
    from trialgauntlet.results import build_results, write_results

    if not 0.0 <= args.threshold <= 1.0:
        raise CLIError("--threshold must be between 0 and 1")
    if args.k > args.n:
        raise CLIError(f"--k ({args.k}) must not exceed --n ({args.n})")
    agents = _csv(args.agents) or list(BASELINES)
    for a in agents:
        if a not in BASELINES:
            raise CLIError(f"unknown baseline '{a}'. known: {', '.join(BASELINES)}")
    envs = resolve_envs(args.env)
    report = run_audit(
        envs,
        agents=agents,
        n=args.n,
        k=args.k,
        threshold=args.threshold,
        metric=args.metric,
        seed=args.seed,
        n_boot=args.n_boot,
    )
    demo_envs = [] if args.no_demo else [f"{e}+naive" for e in envs if "+" not in e]
    if demo_envs:
        run_audit(
            demo_envs,
            agents=agents,
            n=args.n,
            k=args.k,
            threshold=args.threshold,
            metric=args.metric,
            seed=args.seed,
            n_boot=args.n_boot,
            gated=False,
            report=report,
        )
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        md = args.format == "markdown"
        gated = [r for r in report.rows if r.gated]
        demo = [r for r in report.rows if not r.gated]
        print(
            f"Degenerate-success audit: n={report.n} trials/task, k={report.k}, "
            f"FLAG when a trivial baseline exceeds {report.threshold:.1%} {report.metric}\n"
        )
        print(format_table(report, markdown=md, rows=gated))
        if demo:
            print(
                "\nDemonstration only (not gated): the same baselines against a deliberately naive final-state"
                "\ngrader that passes unsolvable tasks whenever the state is unchanged. This is what a degenerate"
                "\nbenchmark looks like.\n"
            )
            print(format_table(report, markdown=md, rows=demo))
        print("\n" + format_summary(report))
    if args.out_dir:
        for key in agents:
            doc = build_results(
                agent={"name": DISPLAY[key], "id": DISPLAY[key], "type": "baseline", "config": {}},
                label="BASELINE",
                summaries=report.summaries[key],
                run={"n": args.n, "k": args.k, "seed": args.seed, "n_boot": args.n_boot, "threshold": args.threshold},
            )
            write_results(args.out_dir / f"baseline-{key}.json", doc)
        print(f"wrote {len(agents)} result file(s) to {args.out_dir}")
    return 0 if (report.ok or args.no_fail) else 1


# ----------------------------------------------------------------------------------- replay
def _expand_paths(paths: Sequence[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(p.rglob("*.jsonl")))
        elif p.exists():
            out.append(p)
        else:
            raise CLIError(f"no such file or directory: {raw}")
    if not out:
        raise CLIError("no trajectory files found")
    return out


@command(
    "replay",
    "replay recorded trajectories and verify they reproduce the identical grade",
    lambda p: p.add_argument("paths", nargs="+", help="trajectory .jsonl files or directories"),
)
def cmd_replay(args: argparse.Namespace) -> int:
    from trialgauntlet.runner import replay_trajectory
    from trialgauntlet.trajectory import TrajectoryError

    files = _expand_paths(args.paths)
    bad = 0
    for path in files:
        try:
            report = replay_trajectory(path)
        except (TrajectoryError, KeyError) as err:
            print(f"ERROR     {path}: {err}")
            bad += 1
            continue
        if report.ok:
            print(f"IDENTICAL {path}")
        else:
            bad += 1
            print(f"MISMATCH  {path}")
            for line in report.mismatches[:10]:
                print(f"    - {line}")
    print(f"{len(files) - bad}/{len(files)} trajectories replay to the identical grade")
    return 1 if bad else 0


# ------------------------------------------------------------------------------------ main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trialgauntlet",
        description="Agent reliability harness: pass^k next to pass@k, with a degenerate-success audit.",
    )
    parser.add_argument("--version", action="version", version=f"trialgauntlet {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")
    for name, (help_text, configure, fn) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        configure(p)
        p.set_defaults(func=fn)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return int(func(args))
    except CLIError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
