from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from helpers import LaxToy, LeakyToy, ToyEnv, ToyGreedy, ToyOracle, UnsolvableToy  # noqa: E402

from trialgauntlet.envs import ENV_FACTORIES, GREEDY, ORACLES, register  # noqa: E402


@pytest.fixture
def toy_env():
    return ToyEnv()


@pytest.fixture
def toy_registered():
    """Register the toy env so spec-string based helpers (replay, suites) can build it."""
    register("toy", ToyEnv)
    yield
    ENV_FACTORIES.pop("toy", None)


@pytest.fixture
def toy_family():
    """Register the toy env and three deliberately broken variants for audit tests."""
    names = {"toy": ToyEnv, "leaky": LeakyToy, "unsolvable": UnsolvableToy, "lax": LaxToy}
    for name, cls in names.items():
        register(name, cls)
        ORACLES[name] = ToyOracle
        GREEDY[name] = ToyGreedy
    yield names
    for name in names:
        ENV_FACTORIES.pop(name, None)
        ORACLES.pop(name, None)
        GREEDY.pop(name, None)
