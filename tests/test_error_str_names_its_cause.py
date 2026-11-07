"""``str()`` of an error says why it happened, because that is what a log line shows.

An error's ``message`` keeps Effect's text ("Failed to insert data"), and its reason or cause
sits in a field; ``str()`` adds it (docs/PARITY.md). ``test_every_error_...`` walks every error
class in pyfect, so a new one that hides its cause fails here."""

import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from types import ModuleType

import pytest
from _pyfect_modules import INSTALLS_ON_IMPORT, module_names

from pyfect.ai import mcp_client_error
from pyfect.errors import TaggedError, UnknownError
from pyfect.eventlog.event_log_session_auth import EventLogSessionAuthError
from pyfect.http import error as http_error
from pyfect.http.multipart import MultipartError, MultipartErrorReason
from pyfect.rpc.client_error import RpcClientDefect, RpcClientError
from pyfect.socket._errors import SocketOpenError
from pyfect.socket.server import SocketServerError, SocketServerOpenError
from pyfect.sql import error as sql_error
from pyfect.sql.error import ConnectionError as SqlConnectionError
from pyfect.sql.error import SqlError
from pyfect.sql.error import UnknownError as SqlUnknownError
from pyfect.workers.worker_error import WorkerSendError


class Refused(Exception):
    pass


WHY = Refused("connection refused")


def test_a_sql_error_names_its_reason():
    error = SqlError(reason=SqlUnknownError(cause=WHY, message="Failed to insert data"))
    assert str(error) == "Failed to insert data: Refused: connection refused"


def test_the_fields_stay_as_they_were():
    reason = SqlConnectionError(cause=WHY, message="Failed to insert data", operation="insert")
    error = SqlError(reason=reason)
    assert error.message == "Failed to insert data"
    assert error.reason is reason
    assert error.cause is reason
    assert reason.message == "Failed to insert data"
    assert reason.cause is WHY
    assert error.__cause__ is reason


def test_a_reason_without_a_message_names_its_tag_and_cause():
    assert str(SqlError(reason=SqlUnknownError(cause=WHY))) == (
        "UnknownError: Refused: connection refused"
    )


def test_a_cause_that_is_not_an_exception_is_shown():
    assert str(SqlError(reason=SqlUnknownError(cause={"code": 7}, message="Failed"))) == (
        "Failed: {'code': 7}"
    )


def test_a_message_that_already_says_why_is_not_repeated():
    error = SqlError(reason=SqlUnknownError(cause=WHY, message="Failed: connection refused"))
    assert str(error) == "Failed: connection refused"


def test_a_raised_cause_shows_in_a_plain_tagged_error():
    assert "boom" in str(UnknownError(cause=ValueError("boom")))


def _modules() -> Iterator[ModuleType]:
    for name in module_names():
        if name in INSTALLS_ON_IMPORT:
            continue
        try:
            yield importlib.import_module(name)
        except BaseException:
            continue


def _error_classes() -> list[type[TaggedError]]:
    found: set[type[TaggedError]] = set()
    for module in _modules():
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, TaggedError)
                and value.__module__.startswith("pyfect")
            ):
                found.add(value)
    return sorted(found, key=lambda c: f"{c.__module__}.{c.__qualname__}")


def _holds_why(cls: type[TaggedError]) -> bool:
    names: set[str] = set()
    for base in cls.__mro__:
        names |= set(getattr(base, "__annotations__", {}))
    return bool({"cause", "reason"} & names) or isinstance(getattr(cls, "cause", None), property)


_OWN_STR_WITH_A_TEST = {
    sql_error._Reason,  # pyright: ignore[reportPrivateUsage]  # the tests above
    http_error._RequestReason,  # pyright: ignore[reportPrivateUsage]  # test_http_client_error_messages
    http_error._ResponseReason,  # pyright: ignore[reportPrivateUsage]  # test_http_client_error_messages
    http_error.HttpClientError,  # test_http_client_error_messages
    SocketOpenError,  # its message says the cause: test_socket_open_errors
    UnknownError,  # test_a_raised_cause_shows_in_a_plain_tagged_error
}


def test_an_error_with_a_cause_keeps_the_str_that_shows_it():
    """An override of ``TaggedError.__str__`` is what hid the cause in every case found."""
    overriding = {
        owner
        for cls in _error_classes()
        if _holds_why(cls)
        for owner in [next(c for c in cls.__mro__ if "__str__" in vars(c))]
        if owner is not TaggedError
    }
    assert overriding == _OWN_STR_WITH_A_TEST


@dataclass(eq=False)
class _Failure(TaggedError):
    """Any error with a message and a cause gets it from ``TaggedError``."""

    cause: object = None

    @property
    def message(self) -> str:
        return "It failed"


INSTANCES = {
    "any": _Failure(WHY),
    "mcp reason": mcp_client_error.TransportError(cause=WHY),
    "mcp error": mcp_client_error.McpClientError(mcp_client_error.TransportError(cause=WHY)),
    "session auth": EventLogSessionAuthError("InvalidPayload", "It failed", WHY),
    "rpc": RpcClientError(RpcClientDefect("It failed", WHY)),
    "multipart": MultipartError(MultipartErrorReason("InternalError", WHY)),
    "socket server": SocketServerError(SocketServerOpenError(WHY)),
    "worker": WorkerSendError(message="It failed", cause=WHY),
}


@pytest.mark.parametrize("error", INSTANCES.values(), ids=INSTANCES.keys())
def test_these_errors_name_their_cause(error: TaggedError):
    assert "connection refused" in str(error)


def test_a_wrapper_says_its_reasons_message_once():
    error = RpcClientError(RpcClientDefect("It failed", WHY))
    assert str(error) == "RpcClientDefect: It failed: Refused: connection refused"
    assert error.message == "RpcClientDefect: It failed"
