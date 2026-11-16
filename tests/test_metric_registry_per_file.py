"""tests/_metric_registry.py: each test file starts from an empty default metric registry.

Under vitest each Effect test file runs in its own module graph, so the default
``MetricRegistry`` starts empty; here one process runs every file. A summary with a NaN
quantile left in it by tests/test_number_order_nan.py made the DevTools client send
nothing in tests/test_log_redaction.py, files later.
"""

from pathlib import Path

import _metric_registry
import pytest


@pytest.fixture(autouse=True)
def _plugin_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(_metric_registry.__file__).parent))


_LEAVES = """
import pyfect as fx
from pyfect import metric


def test_updates_a_counter():
    fx.run_blocking(metric.counter("left-behind").update(1))
"""

_FINDS = """
import pyfect as fx
from pyfect import metric


def test_finds_no_series():
    assert fx.run_blocking(metric.snapshot) == []
"""


def test_a_file_does_not_see_the_metrics_an_earlier_file_left(pytester: pytest.Pytester):
    pytester.makepyfile(test_a_leaves=_LEAVES, test_b_finds=_FINDS)
    result = pytester.runpytest_subprocess("-p", "_metric_registry")
    result.assert_outcomes(passed=2)
