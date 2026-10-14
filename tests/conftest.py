from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from helpers import ToyEnv  # noqa: E402

from trialgauntlet.envs import ENV_FACTORIES, register  # noqa: E402


@pytest.fixture
def toy_env():
    return ToyEnv()


@pytest.fixture
def toy_registered():
    """Register the toy env so spec-string based helpers (replay, suites) can build it."""
    register("toy", ToyEnv)
    yield
    ENV_FACTORIES.pop("toy", None)
