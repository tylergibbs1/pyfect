"""Port of Effect's ``OtlpEnvHeaders.test.ts``; the docstring is the
Effect test title. ``OtlpEnv`` is the internal ``_otlp_env``."""

from __future__ import annotations

import pyfect as fx
from pyfect import config_provider
from pyfect.observability import _otlp_env


def test_decodes_percent_encoded_otlp_header_values() -> None:
    """decodes percent-encoded OTLP header values"""
    provider = config_provider.from_env(
        {"OTEL_EXPORTER_OTLP_TRACES_HEADERS": "authorization=Bearer%20token,x-comma=comma%2Cvalue"}
    )
    headers = fx.run_sync(_otlp_env.headers("TRACES").parse(provider).or_die())
    assert headers == {"authorization": "Bearer token", "x-comma": "comma,value"}
