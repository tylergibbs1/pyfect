"""The listen log is ``serve``'s alone (``disable_listen_log``), as Effect's
``NodeHttpServer`` logs nothing itself: no ASGI engine prints a startup line of
its own. hypercorn's "Running on" line printed even with
``disable_listen_log=True`` (graft #7)."""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect.http import hypercorn_server, router, server, server_response, uvicorn_server
from pyfect.scope import scoped

_ENGINES: dict[str, Callable[..., fx.Layer[Any, Any, Any]]] = {
    "uvicorn": uvicorn_server.layer_test,
    "hypercorn": hypercorn_server.layer_test,
}


@pytest.mark.parametrize("engine", sorted(_ENGINES))
def test_an_engine_logs_no_startup_line_of_its_own(
    engine: str, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    routes: fx.Layer[Any, Any, Any] = router.add("GET", "/hello", server_response.text("hi"))
    served = router.serve(routes, disable_logger=True, disable_listen_log=True)
    program = scoped(server.HttpServer().pipe(fx.provide(served)))
    fx.run_blocking(program.pipe(fx.provide(_ENGINES[engine]())).or_die())
    out, err = capfd.readouterr()
    assert "running on" not in (out + err + caplog.text).lower()
