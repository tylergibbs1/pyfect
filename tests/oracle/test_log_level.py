"""Ports of Effect's ``effect/test/LogLevel.test.ts``. Each test's docstring is the
Effect test title."""

import pyfect as fx
from pyfect import testing


@testing.effect
def test_uses_info_as_the_default_minimum_log_level():
    """uses Info as the default minimum log level"""
    assert not (yield from fx.LogLevel.DEBUG.is_enabled())
    assert (yield from fx.LogLevel.INFO.is_enabled())
    assert (yield from fx.LogLevel.ERROR.is_enabled())


@testing.effect
def test_supports_all_and_none_sentinel_thresholds():
    """supports All and None sentinel thresholds"""
    debug_enabled, warn_enabled, error_enabled = yield from fx.all(
        fx.LogLevel.DEBUG.is_enabled(),
        fx.LogLevel.WARN.is_enabled(),
        fx.LogLevel.ERROR.is_enabled(),
    ).pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.WARN))
    assert not debug_enabled
    assert warn_enabled
    assert error_enabled
