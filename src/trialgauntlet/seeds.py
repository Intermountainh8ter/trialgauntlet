"""Seed derivation. SHA-256 based so it is stable across Python versions and platforms."""

from __future__ import annotations

import hashlib
import random


def derive_seed(*parts: object) -> int:
    """Derive a 31-bit seed from arbitrary printable parts."""
    text = "\x1f".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big") & 0x7FFFFFFF


def rng_for(*parts: object) -> random.Random:
    """A ``random.Random`` seeded from ``parts`` (string seeds are hashed by SHA-512 in CPython)."""
    return random.Random(derive_seed(*parts))
