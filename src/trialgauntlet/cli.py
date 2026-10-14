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
    llm = p.add_argument_group("LLM agent (--agent llm): any OpenAI-compatible /v1/chat/completions server")
    llm.add_argument("--base-url", help="e.g. http://127.0.0.1:8080/v1 (llama-server --jinja, vLLM, Ollama)")
    llm.add_argument("--model", help="model name sent to the server (default: first model the server lists)")
    llm.add_argument("--temperature", type=float, default=0.0)
    llm.add_argument("--top-p", type=float)
    llm.add_argument("--max-tokens", type=int, default=1024, help="completion tokens per request")
    llm.add_argument("--timeout", type=float, default=120.0, help="seconds per request")
    llm.add_argument("--retries", type=int, default=3, help="retries per request on connection errors, 429, 5xx")
    llm.add_argument("--api-key-env", help="name of the environment variable holding the API key (if any)")
    llm.add_argument("--parse-text-tools", action="store_true", help="accept tool calls written as text (lenient)")
    llm.add_argument("--extra-body", help="JSON object merged into every request, e.g. '{\"top_k\": 20}'")
    llm.add_argument("--label", choices=["REAL", "MOCK"], help="force the MOCK label (detected automatically)")
    llm.add_argument("--max-trial-tokens", type=int, help="token budget per trial")
    llm.add_argument("--max-trial-seconds", type=float, help="wall-clock budget per trial")
    llm.add_argument("--price-in", type=float, default=0.0, help="USD per million prompt tokens")
    llm.add_argument("--price-out", type=float, default=0.0, help="USD per million completion tokens")
    llm.add_argument("--quiet", action="store_true", help="no per-task progress on stderr")


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


def _build_llm(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    import os

    from trialgauntlet.agents.llm import LLMConfig, http_json, models_url

    if not args.base_url:
        raise CLIError("--agent llm needs --base-url, e.g. --base-url http://127.0.0.1:8080/v1")
    key = None
    if args.api_key_env:
        key = os.environ.get(args.api_key_env)
        if not key:
            raise CLIError(f"environment variable {args.api_key_env} is not set")
    extra: dict = {}
    if args.extra_body:
        try:
            extra = json.loads(args.extra_body)
        except json.JSONDecodeError as err:
            raise CLIError(f"--extra-body is not valid JSON: {err}") from err
        if not isinstance(extra, dict):
            raise CLIError("--extra-body must be a JSON object")
    model = args.model
    if not model:
        try:
            listing = http_json(
                models_url(args.base_url), None, {"Authorization": f"Bearer {key}"} if key else {}, 30, "GET"
            )
            model = listing["data"][0]["id"]
        except Exception as err:  # noqa: BLE001 - any failure here is reported with its cause
            raise CLIError(f"--model not given and the server's model list could not be read: {err}") from err
        print(f"using model '{model}' (first model the server lists)", file=sys.stderr)
    return LLMConfig(
        base_url=args.base_url,
        model=model,
        api_key=key,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        retries=args.retries,
        parse_text_tools=args.parse_text_tools,
        extra_body=extra,
    )


@command("run", "run an agent on environments and print/write pass@1, pass@k, pass^k", _cfg_run)
def cmd_run(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    from trialgauntlet.agents.llm import LLMAgent, LLMError
    from trialgauntlet.agents.registry import ALL_AGENTS, DISPLAY, EXTRA, make_baseline
    from trialgauntlet.budget import Budget
    from trialgauntlet.envs import make_env
    from trialgauntlet.harness import evaluate_env, select_seeds
    from trialgauntlet.results import build_results, write_results

    is_llm = args.agent == "llm"
    if not is_llm and args.agent not in ALL_AGENTS:
        raise CLIError(f"unknown agent '{args.agent}'. known: llm, {', '.join(ALL_AGENTS)}")
    if args.k > args.n:
        raise CLIError(f"--k ({args.k}) must not exceed --n ({args.n}): pass^k needs at least k trials per task")
    envs = expand_specs(resolve_envs(args.env), args.inject, args.fault)
    envs = resolve_envs(",".join(envs))
    cfg = _build_llm(args) if is_llm else None
    created: list[LLMAgent] = []

    def llm_factory() -> LLMAgent:
        agent = LLMAgent(cfg)  # type: ignore[arg-type]
        created.append(agent)
        return agent

    summaries = {}
    agent_info: dict = {}
    try:
        for spec in envs:
            base = spec.split("+", 1)[0]
            factory = llm_factory if is_llm else make_baseline(args.agent, base)
            env = make_env(spec)
            try:
                seeds = select_seeds(spec, tiers=_csv(args.tiers), kinds=_csv(args.kinds), limit=args.limit)
            except ValueError as err:
                raise CLIError(str(err)) from err
            budget = Budget(
                max_steps=args.max_steps or env.default_max_steps,
                max_tokens=args.max_trial_tokens,
                max_seconds=args.max_trial_seconds,
            )
            probe = factory()
            if is_llm:
                agent_info = {
                    "name": cfg.model,  # type: ignore[union-attr]
                    "id": probe.agent_id(),
                    "type": "llm",
                    "model": cfg.model,  # type: ignore[union-attr]
                    "temperature": cfg.temperature,  # type: ignore[union-attr]
                    "config": probe.config(),
                    "base_url": cfg.base_url,  # type: ignore[union-attr]
                }
            else:
                agent_info = {
                    "name": DISPLAY.get(args.agent) or EXTRA[args.agent],
                    "id": probe.agent_id(),
                    "type": "baseline",
                    "config": probe.config(),
                }
            progress = None
            if is_llm and not args.quiet:
                tasks = {t.seed: t for t in env.task_specs()}

                def progress(result, resumed, spec=spec, tasks=tasks):  # type: ignore[no-redef]
                    if result.trial == args.n - 1:
                        t = tasks[result.task_seed]
                        print(
                            f"[{spec}] task {result.task_seed} ({t.tier} {t.kind}) done"
                            + (" (resumed)" if resumed else ""),
                            file=sys.stderr,
                        )

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
                include_timing=is_llm,
                price_in_per_m=args.price_in,
                price_out_per_m=args.price_out,
                on_trial=progress,
            )
            summaries[spec] = summary
            print_env_summary(spec, summary)
    except LLMError as err:
        resume = (
            " Completed trials are kept; re-run the same command to resume."
            if args.run_dir
            else " Use --run-dir to make runs resumable."
        )
        raise CLIError(f"{err}.{resume}") from err
    label = "BASELINE"
    if is_llm:
        mock = any(a.is_mock for a in created) or args.label == "MOCK"
        if args.label == "REAL" and mock:
            raise CLIError("--label REAL was requested but the server identified itself as the built-in mock")
        label = "MOCK" if mock else "REAL"
        if label == "MOCK":
            print("MOCK run: scripted server replies; this says nothing about any model.", file=sys.stderr)
    if args.out:
        run = {"n": args.n, "k": args.k, "seed": args.seed, "n_boot": args.n_boot}
        if is_llm:
            run["created"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        doc = build_results(agent=agent_info, label=label, summaries=summaries, run=run)
        write_results(args.out, doc)
        print(f"wrote {args.out} (label {label})")
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


# ----------------------------------------------------------------------------------- doctor
def _cfg_doctor(p: argparse.ArgumentParser) -> None:
    p.add_argument("--base-url", required=True)
    p.add_argument("--model")
    p.add_argument("--api-key-env")
    p.add_argument("--timeout", type=float, default=60.0)


@command("doctor", "check that a model server speaks OpenAI tool calling before you start a long run", _cfg_doctor)
def cmd_doctor(args: argparse.Namespace) -> int:
    import os
    import time

    from trialgauntlet.agents.llm import (
        MOCK_FINGERPRINT_PREFIX,
        LLMError,
        chat_url,
        http_json,
        looks_like_text_tool_call,
        models_url,
    )

    key = os.environ.get(args.api_key_env) if args.api_key_env else None
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    ok = True

    def report(status: str, text: str) -> None:
        print(f"[{status}] {text}")

    model = args.model
    try:
        listing = http_json(models_url(args.base_url), None, headers, args.timeout, "GET")
        ids = [m.get("id") for m in listing.get("data", []) if isinstance(m, dict)]
        report("PASS", f"server reachable; models: {', '.join(map(str, ids)) or '(none listed)'}")
        model = model or (ids[0] if ids else None)
    except LLMError as err:
        report("FAIL", str(err))
        print(
            "Fix: start the server and check --base-url (llama.cpp: llama-server --jinja -m <model.gguf> --port 8080)."
        )
        return 1
    if not model:
        report("FAIL", "no model name: pass --model")
        return 1
    tool = {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echo a word back.",
            "parameters": {
                "type": "object",
                "properties": {"word": {"type": "string"}},
                "required": ["word"],
                "additionalProperties": False,
            },
        },
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Call the echo tool with the word ok. Do not answer in prose."}],
        "tools": [tool],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 256,
        "seed": 1,
    }
    started = time.monotonic()
    try:
        resp = http_json(chat_url(args.base_url), body, headers, args.timeout)
    except LLMError as err:
        report("FAIL", f"chat request failed: {err}")
        return 1
    latency = time.monotonic() - started
    message = (resp.get("choices") or [{}])[0].get("message", {})
    calls = message.get("tool_calls") or []
    usage = resp.get("usage") or {}
    if calls:
        fn = calls[0].get("function", {})
        args_raw = fn.get("arguments")
        try:
            parsed = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            good = isinstance(parsed, dict) and fn.get("name") == "echo"
        except json.JSONDecodeError:
            good = False
        if good:
            report("PASS", f"structured tool call received ({fn.get('name')}({parsed})) in {latency:.2f}s")
        else:
            ok = False
            report("FAIL", f"tool call arrived but is malformed: {fn}")
    elif looks_like_text_tool_call(message.get("content") or ""):
        ok = False
        report("FAIL", "the server returned the tool call as plain text instead of a structured tool_calls field")
        print("Fix: llama.cpp: restart llama-server with --jinja (and a model whose chat template supports tools);")
        print("     vLLM: --enable-auto-tool-choice --tool-call-parser <parser>; Ollama: use a tool-capable model.")
        print("     As a last resort pass --parse-text-tools to trialgauntlet run (results then say so).")
    else:
        ok = False
        report(
            "FAIL", f"the model answered in prose and did not call the tool: {(message.get('content') or '')[:120]!r}"
        )
    if usage:
        report("INFO", f"usage reported: {usage}")
    else:
        report("WARN", "the server reports no token usage; token and cost columns will be zero")
    if str(resp.get("system_fingerprint", "")).startswith(MOCK_FINGERPRINT_PREFIX):
        report("INFO", "this is the built-in MOCK server: runs against it are labelled MOCK")
    return 0 if ok else 1


# ------------------------------------------------------------------------------ mock server
def _cfg_mock(p: argparse.ArgumentParser) -> None:
    from trialgauntlet.mockserver import MODES

    p.add_argument("--mode", default="oracle", choices=MODES)
    p.add_argument("--port", type=int, default=8089)
    p.add_argument("--flaky", type=float, default=0.05, help="per-step failure probability for --mode flaky")
    p.add_argument("--fail-first", type=int, default=2, help="requests that fail with HTTP 500 for --mode http500")


@command("mock-server", "start the scripted mock OpenAI-compatible server (results are labelled MOCK)", _cfg_mock)
def cmd_mock_server(args: argparse.Namespace) -> int:  # pragma: no cover - blocks until interrupted
    from trialgauntlet.mockserver import serve

    serve(args.mode, args.port, args.flaky, args.fail_first)
    return 0


# --------------------------------------------------------------------------------- report
def _cfg_report(p: argparse.ArgumentParser) -> None:
    p.add_argument("paths", nargs="*", type=Path, default=[Path("results")], help="result files or directories")
    p.add_argument("--out-dir", type=Path, default=Path("report"))
    p.add_argument("--threshold", type=float, help="audit threshold (default: the one recorded in each result file)")
    p.add_argument("--print", dest="show", action="store_true", help="also print the markdown")


@command("report", "render results/*.json into report.md plus SVG charts (refuses if there are none)", _cfg_report)
def cmd_report(args: argparse.Namespace) -> int:
    from trialgauntlet.report import ReportError, collect, write_report

    try:
        entries = collect(args.paths)
        written = write_report(entries, args.out_dir, args.threshold)
    except ReportError as err:
        raise CLIError(str(err)) from err
    for path in written:
        print(f"wrote {path}")
    if args.show:
        print()
        print(written[0].read_text(encoding="utf-8"))
    return 0


# ----------------------------------------------------------------------------- leaderboard
def _cfg_leaderboard(p: argparse.ArgumentParser) -> None:
    p.add_argument("paths", nargs="*", type=Path, default=[Path("results")])
    p.add_argument("--out", type=Path, default=Path("leaderboard.json"))
    p.add_argument("--include-mock", action="store_true", help="include MOCK runs (flagged mock: true)")
    p.add_argument("--validate", type=Path, help="validate an existing leaderboard.json and exit")


@command("leaderboard", "build (or --validate) leaderboard.json from result files", _cfg_leaderboard)
def cmd_leaderboard(args: argparse.Namespace) -> int:
    from trialgauntlet.leaderboard import LeaderboardError, build_leaderboard, load_leaderboard, write_leaderboard
    from trialgauntlet.report import ReportError, collect

    try:
        if args.validate:
            doc = load_leaderboard(args.validate)
            print(f"{args.validate}: valid, {len(doc['entries'])} entries")
            return 0
        doc = build_leaderboard(collect(args.paths), include_mock=args.include_mock)
        write_leaderboard(args.out, doc)
    except (ReportError, LeaderboardError) as err:
        raise CLIError(str(err)) from err
    print(f"wrote {args.out} ({len(doc['entries'])} entries)")
    return 0


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
