"""The ASGI engines take their shutdown timeouts as seconds: a ``Duration`` handed to
uvicorn's or hypercorn's untyped config breaks their shutdown (uvicorn's
``Server._wait_tasks_to_complete`` is never awaited)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("uvicorn")
pytest.importorskip("hypercorn")

from pyfect.http import hypercorn_server, uvicorn_server


def _no_app(*_: Any) -> None:
    return None


def test_uvicorn_gets_its_graceful_shutdown_timeout_in_seconds():
    config = uvicorn_server._uvicorn(_no_app, {"graceful_shutdown_timeout": "2 seconds"}).config  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    assert config.timeout_graceful_shutdown == 2.5


def test_hypercorn_gets_its_graceful_timeout_in_seconds():
    engine = hypercorn_server._Hypercorn(_no_app, {"graceful_shutdown_timeout": "2 seconds"})  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    assert engine.config.graceful_timeout == 2.5
