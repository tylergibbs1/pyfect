"""Ports of Effect's ``packages/ai/openai/test/OpenAiTelemetry.test.ts``."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.ai.openai import telemetry
from pyfect.tracer import NativeSpan, current_span


@testing.effect
def test_attribute_keys():
    """OpenAiTelemetry / writes current OpenAI GenAI attribute keys"""

    def body() -> Any:
        span = yield from current_span()
        telemetry.add_gen_ai_annotations(
            span,
            {
                "provider": {"name": "openai"},
                "openai": {
                    "request": {"service_tier": "auto"},
                    "response": {"service_tier": "default", "system_fingerprint": "fp_1"},
                },
            },
        )
        assert isinstance(span, NativeSpan)
        assert span.attributes == {
            "gen_ai.provider.name": "openai",
            "openai.request.service_tier": "auto",
            "openai.response.service_tier": "default",
            "openai.response.system_fingerprint": "fp_1",
        }

    yield from fx.gen(body).with_span("test")
