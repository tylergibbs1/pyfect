"""Ports of Effect's ``http/HttpServerRespondable.test.ts``. Each test's
docstring is the Effect test title."""

import pyfect as fx
from pyfect.exit import Failure
from pyfect.http import server_response
from pyfect.http.server_respondable import to_response_or_else
from pyfect.schema import SchemaError, String, decode_unknown_effect


def test_maps_schema_error_to_a_400_response() -> None:
    """maps SchemaError to a 400 response"""
    exit = fx.run_sync_exit(decode_unknown_effect(String)(123))
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, SchemaError)
    fallback = server_response.empty(status=500)
    assert fx.run_sync(to_response_or_else(error, fallback)).status == 400


def test_falls_back_for_other_errors() -> None:
    """falls back for other errors"""
    fallback = server_response.empty(status=500)
    assert fx.run_sync(to_response_or_else(RuntimeError("boom"), fallback)) is fallback
