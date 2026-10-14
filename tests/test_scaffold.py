from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import trialgauntlet
from trialgauntlet import cli

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_semver_like():
    parts = trialgauntlet.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert trialgauntlet.__version__ in capsys.readouterr().out


def test_cli_without_arguments_prints_help_and_fails(capsys):
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_python_dash_m_entry_point():
    out = subprocess.run(
        [sys.executable, "-m", "trialgauntlet", "--version"], capture_output=True, text=True, check=True
    )
    assert "trialgauntlet" in out.stdout


def test_license_is_mit_with_author():
    text = (ROOT / "LICENSE").read_text()
    assert text.startswith("MIT License")
    assert "Ammon Jackson" in text


def test_methodology_documents_core_formulas():
    text = (ROOT / "docs" / "METHODOLOGY.md").read_text()
    for needle in ("C(c, k) / C(n, k)", "pass^k", "pass@k", "degenerate-success", "Rao-Blackwell"):
        assert needle in text


def test_gitignore_excludes_local_runs():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert "runs/" in lines and "__pycache__/" in lines


def test_core_has_no_runtime_dependencies():
    text = (ROOT / "pyproject.toml").read_text()
    assert "dependencies = []" in text


def test_runtime_code_imports_only_the_standard_library():
    """No third-party import anywhere under src (numpy included): the runtime has no dependencies."""
    import ast
    import sys

    stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
    for path in (ROOT / "src" / "trialgauntlet").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                assert name == "trialgauntlet" or stdlib is None or name in stdlib, f"{path.name} imports {name}"
                assert name != "numpy"
