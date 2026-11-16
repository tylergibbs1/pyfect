"""Each test file starts from an empty default metric registry, as each Effect test file
does under vitest, which runs every file in its own module graph. Here one process runs them
all, and a series one file left (a summary with a NaN quantile, say) reached every snapshot
after it: the DevTools client, which sends one, sent nothing. The registry is put back after
the file. ``tests/test_metric_registry_per_file.py`` pins this.
"""

from collections.abc import Iterator

import pytest

import pyfect as fx
from pyfect.metric import MetricRegistry


@pytest.fixture(autouse=True, scope="module")
def metrics_start_empty() -> Iterator[None]:
    registry = fx.run_blocking(MetricRegistry())
    saved = dict(registry)
    registry.clear()
    yield
    registry.clear()
    registry.update(saved)
