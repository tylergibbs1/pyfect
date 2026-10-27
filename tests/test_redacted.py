"""A ``Redacted`` secret never prints: not through the loggers (every
format, the console loggers and the ``logging`` bridge), not in
``Cause.pretty``, and not inside the errors and containers that carry it.
Also the wipe and equality edges Effect's tests leave out."""

import logging
from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import logger, redacted, testing
from pyfect.console import CurrentConsole

SECRET = "sk-live-0123456789"


@dataclass
class LoginFailed(fx.TaggedError):
    token: fx.Redacted[str]


def secret() -> fx.Redacted[str]:
    return redacted.make(SECRET, label="token")


@pytest.mark.parametrize(
    "format_",
    [logger.format_simple, logger.format_logfmt, logger.format_json],
    ids=["simple", "logfmt", "json"],
)
@testing.effect
def test_text_loggers_print_the_placeholder(format_: fx.Logger[str]):
    lines: list[str] = []
    yield from fx.log("login", secret(), {"nested": [secret()]}, fx.cause.fail(secret())).pipe(
        fx.provide(logger.layer([format_.map(lines.append)]))
    )
    assert len(lines) == 1
    assert SECRET not in lines[0]
    assert "<redacted:token>" in lines[0]


@testing.effect
def test_console_loggers_print_the_placeholder():
    console = testing.TestConsole()
    loggers = [logger.console_pretty(colors=False), logger.console_json, logger.console_logfmt]
    yield from (
        fx.log("login", secret(), fx.cause.fail(LoginFailed(secret())))
        .annotate_logs("token", secret())
        .pipe(fx.provide(logger.layer(loggers)))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    printed = " ".join(str(arg) for _, args in console.entries for arg in args)
    assert "<redacted:token>" in printed
    assert SECRET not in printed


@testing.effect
def test_the_logging_bridge_prints_the_placeholder(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO, logger="pyfect.redacted"):
        yield from fx.log("login", secret(), fx.cause.fail(LoginFailed(secret()))).pipe(
            fx.provide(logger.layer([logger.to_logging("pyfect.redacted")]))
        )
    assert "<redacted:token>" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "cause",
    [
        fx.cause.fail(secret()),
        fx.cause.fail(LoginFailed(secret())),
        fx.cause.die(LoginFailed(secret())),
        fx.cause.fail({"token": secret()}),
    ],
    ids=["value", "error-field", "defect", "container"],
)
def test_cause_pretty_prints_the_placeholder(cause: fx.Cause[object]):
    pretty = cause.pretty()
    assert "<redacted:token>" in pretty
    assert SECRET not in pretty


def test_reprs_of_carriers_print_the_placeholder():
    error = LoginFailed(secret())
    for text in (str(error), repr(error), repr([secret()]), f"{secret()!r}", f"{secret():>30}"):
        assert SECRET not in text


def test_an_empty_label_is_no_label():
    assert str(redacted.make(SECRET, label="")) == "<redacted>"
    assert redacted.make(SECRET, label="").label is None


def test_wipe_unsafe_reports_whether_a_value_was_there():
    token = secret()
    assert redacted.wipe_unsafe(token)
    assert not redacted.wipe_unsafe(token)


def test_wiping_one_copy_leaves_an_equal_copy_readable():
    first, second = secret(), secret()
    redacted.wipe_unsafe(first)
    assert redacted.value(second) == SECRET
