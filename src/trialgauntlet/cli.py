"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from trialgauntlet import __version__


class CLIError(Exception):
    """A user-facing error: printed without a traceback, exit status 2."""


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


def cmd_replay(args: argparse.Namespace) -> int:
    from trialgauntlet.runner import replay_trajectory
    from trialgauntlet.trajectory import TrajectoryError

    bad = 0
    for path in _expand_paths(args.paths):
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
    total = len(_expand_paths(args.paths))
    print(f"{total - bad}/{total} trajectories replay to the identical grade")
    return 1 if bad else 0


COMMANDS: dict[str, tuple[str, Callable[[argparse.ArgumentParser], None], Callable[[argparse.Namespace], int]]] = {}


def command(name: str, help_text: str, configure: Callable[[argparse.ArgumentParser], None] = lambda p: None):
    def deco(fn: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
        COMMANDS[name] = (help_text, configure, fn)
        return fn

    return deco


command(
    "replay",
    "replay recorded trajectories and verify they reproduce the identical grade",
    lambda p: p.add_argument("paths", nargs="+", help="trajectory .jsonl files or directories"),
)(cmd_replay)


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
