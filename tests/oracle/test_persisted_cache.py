"""Ports of Effect's ``test/persistence/PersistedCache.test.ts``: the
``persistence/PersistedCacheTest.ts`` suite (``_persisted_cache_suite``) on
``persistence.layer_memory`` (``PersistedCache (memory)``).

Each test's docstring is the Effect test title; the two stale-schema
titles are the ``outcome`` parameters.
"""

from typing import Literal

import pytest

from pyfect.persistence import persistence

from . import _persisted_cache_suite as suite

_LAYER = persistence.layer_memory


def test_smoke_test() -> None:
    """smoke test"""
    suite.run(_LAYER, suite.smoke_test)


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_recomputes_and_replaces_entries_with_stale_schemas(
    outcome: Literal["success", "error"],
) -> None:
    """recomputes and replaces entries with stale ${outcome} schemas"""
    suite.run(_LAYER, suite.recomputes_stale("memory", outcome))


def test_require_services_at_lookup_requires_lookup_services_at_get_time() -> None:
    """requireServicesAt: 'lookup' requires lookup services at get-time"""
    suite.run(_LAYER, suite.require_services_at_lookup("memory"))
