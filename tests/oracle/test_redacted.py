"""Ports of Effect's ``Redacted.test.ts``. Each test's docstring is the
Effect test title. ``Equal.equals`` is ``==``, ``Hash.hash`` is ``hash``,
a ``Chunk`` is a ``tuple``, ``String(r)`` is ``str(r)`` and
``JSON.stringify`` is ``logger.format_json``'s rendering of a logged
value (Python's ``json`` module has no ``toJSON`` hook).

Every title is ported.
"""

import json

import pytest

from pyfect import redacted
from pyfect.logger._text import json_text


def test_chunk_constructor() -> None:
    """chunk constructor"""
    secret = redacted.make(tuple("redacted"))
    assert secret == redacted.make(tuple("redacted"))


def test_value() -> None:
    """value"""
    secret = redacted.make(tuple("redacted"))
    assert redacted.value(secret) == tuple("redacted")


def test_pipe_supports_extracting_the_protected_value() -> None:
    """pipe supports extracting the protected value"""
    value = {"asd": 123}
    secret = redacted.make(value)
    assert secret.pipe(redacted.value) is value


def test_to_string_returns_a_redacted_placeholder() -> None:
    """toString returns a redacted placeholder"""
    secret = redacted.make("redacted")
    assert f"{secret}" == "<redacted>"


def test_to_json_serializes_the_redacted_placeholder() -> None:
    """toJSON serializes the redacted placeholder"""
    secret = redacted.make("redacted")
    assert json_text(secret) == '"<redacted>"'


def test_label_appears_in_redacted_output_and_wipe_errors() -> None:
    """label appears in redacted output and wipe errors"""
    secret = redacted.make("redacted", label="MY_LABEL")
    assert secret.label == "MY_LABEL"
    assert str(secret) == "<redacted:MY_LABEL>"
    assert json.loads(json_text(secret)) == "<redacted:MY_LABEL>"
    assert redacted.wipe_unsafe(secret)
    with pytest.raises(ValueError, match=r'^Unable to get redacted value with label: "MY_LABEL"$'):
        redacted.value(secret)


def test_wipe_unsafe_removes_access_to_the_protected_value() -> None:
    """wipeUnsafe removes access to the protected value"""
    secret = redacted.make("redacted")
    assert redacted.wipe_unsafe(secret)
    with pytest.raises(ValueError, match=r"^Unable to get redacted value$"):
        redacted.value(secret)


def test_equal_compares_the_protected_values_of_two_redacted_values() -> None:
    """Equal compares the protected values of two Redacted values"""
    assert redacted.make(1) == redacted.make(1)
    assert redacted.make(1) != redacted.make(2)


def test_hash_is_derived_from_the_protected_value() -> None:
    """Hash is derived from the protected value"""
    assert hash(redacted.make(1)) == hash(redacted.make(1))
    assert hash(redacted.make(1)) != hash(redacted.make(2))
