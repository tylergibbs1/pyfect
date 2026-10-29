"""Ports of Effect's ``httpapi/HttpApiError.test.ts``.

Each test's docstring is the Effect test title.
"""

from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import effect, error_reporter
from pyfect import schema as S
from pyfect.exit import Failure
from pyfect.http.server_respondable import to_response
from pyfect.http_api.error import HttpApiSchemaError


class _Named(TypedDict):
    name: str


def _flip(eff: fx.Effect[Any, HttpApiSchemaError]) -> HttpApiSchemaError:
    exit_ = fx.run_sync_exit(eff)
    assert isinstance(exit_, Failure)
    error = exit_.cause.squash()
    assert isinstance(error, HttpApiSchemaError)
    return error


def _reported(error: HttpApiSchemaError) -> tuple[fx.Exit[Any, Any], list[fx.Cause[object]]]:
    reports: list[fx.Cause[object]] = []
    reporter = error_reporter.make(lambda report: reports.append(report.cause))
    exit_ = fx.run_sync(
        effect.fail(error)
        .with_error_reporting()
        .exit()
        .pipe(fx.provide(error_reporter.layer([reporter])))
    )
    return exit_, reports


@pytest.mark.parametrize("kind", ["Params", "Headers", "Query", "Payload"])
def test_responds_with_400_and_does_not_report_decoding_failures(kind: Any) -> None:
    """responds with 400 and does not report ${kind} decoding failures"""
    error = _flip(
        HttpApiSchemaError.wrap(kind, S.decode_unknown_effect(S.Struct(_Named))({"name": 123}))
    )
    exit_, reports = _reported(error)
    assert error.kind == kind
    assert isinstance(exit_, Failure)
    assert exit_.cause.squash() is error
    assert reports == []
    assert fx.run_sync(to_response(error)).status == 400


def _encoding_error(kind: Any) -> HttpApiSchemaError:
    return _flip(HttpApiSchemaError.wrap(kind, S.encode_unknown_effect(S.Int)(1.5)))


@pytest.mark.parametrize("kind", ["Body", "ResponseHeaders"])
def test_responds_with_500_for_encoding_failures(kind: Any) -> None:
    """responds with 500 for ${kind} encoding failures"""
    assert fx.run_sync(to_response(_encoding_error(kind))).status == 500


@pytest.mark.parametrize("kind", ["Body", "ResponseHeaders"])
def test_reports_encoding_failures(kind: Any) -> None:
    """reports ${kind} encoding failures"""
    error = _encoding_error(kind)
    exit_, reports = _reported(error)
    assert isinstance(exit_, Failure)
    assert len(reports) == 1
    assert reports[0].squash() is error
