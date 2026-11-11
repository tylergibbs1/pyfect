"""Hypothesis profiles for the property suite.

``pyfect-ci`` (the default) runs a modest, derandomized number of examples, so a failure in CI
reproduces on any machine with the same command. ``PYFECT_HYPOTHESIS_PROFILE=deep`` runs many
more random examples for nightly or local deep runs; a failure there prints the
``@reproduce_failure`` blob and the seed to rerun it with ``--hypothesis-seed``. A deep run
outlasts the suite's 60 s hang alarm, so raise it::

    PYFECT_HYPOTHESIS_PROFILE=deep uv run pytest tests/properties -o test_timeout=1800
"""

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "pyfect-ci",
    max_examples=40,
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "deep",
    max_examples=1_000,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("PYFECT_HYPOTHESIS_PROFILE", "pyfect-ci"))
