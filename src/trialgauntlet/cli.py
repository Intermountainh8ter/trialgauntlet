"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from trialgauntlet import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trialgauntlet",
        description="Agent reliability harness: pass^k next to pass@k, with a degenerate-success audit.",
    )
    parser.add_argument("--version", action="version", version=f"trialgauntlet {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help(sys.stderr)
    return 2
