"""A test server shared by every test of the process, started on first use.

A start that finds what it needs missing (``absent``: no binary, no Docker, no driver) skips
the test with the reason, and every later test with it. A start that ends any other way (an
error, a container that stopped or did not serve in time: ``_docker.ContainerFailed``) fails
the test, and every later test fails at once with that error instead of starting the server
again. The start runs with the test's hang alarm stopped (``_timeout.suspended``): it waits
on its own deadline, so a server that does not come up fails with its state and logs, not as
a test that hung. Each server module calls ``SharedServer.get`` from its ``server()``.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field

import _timeout
import pytest


@dataclass
class SharedServer[S]:
    name: str
    """What a skip or failure calls the server: ``"local PostgreSQL"``."""
    driver: str
    """The client module the tests need; without it they skip."""
    absent: tuple[type[Exception], ...]
    """The errors of a start that found something missing: they skip."""
    _server: S | None = field(default=None, init=False)
    _skip: str | None = field(default=None, init=False)
    _failure: str | None = field(default=None, init=False)

    def get(self, start: Callable[[], S]) -> S:
        if self._server is not None:
            return self._server
        if self._skip is not None:
            pytest.skip(self._skip)
        if self._failure is not None:
            pytest.fail(f"{self.name} did not start in an earlier test: {self._failure}")
        try:
            importlib.import_module(self.driver)
            with _timeout.suspended():
                self._server = start()
        except (ImportError, *self.absent) as error:
            self._skip = f"no {self.name}: {error}"
        except (Exception, pytest.fail.Exception) as error:
            self._failure = f"{error}" or type(error).__name__
            raise
        if self._server is None:
            pytest.skip(self._skip or f"no {self.name}")
        return self._server

    def forget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Start again on next use, for this test only."""
        for attribute in ("_server", "_skip", "_failure"):
            monkeypatch.setattr(self, attribute, None)
