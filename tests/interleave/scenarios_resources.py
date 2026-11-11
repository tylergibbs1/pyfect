"""Interleaving scenarios for Pool, RcRef, RcMap, ScopedRef, Cache, ScopedCache, Layer memoization and acquire_release / uninterruptible_mask (README.md)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from ._harness import Scenario

SCENARIOS: list[Scenario] = []
