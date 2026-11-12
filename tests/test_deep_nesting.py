"""Every parser of untrusted nested text either reads deep input or rejects it
with its documented error: never ``RecursionError``. Recursive parsers wrap
their entry in ``_nesting.parse_nested`` and recurse through
``_stack.with_fresh_stack``. A new nested-text parser belongs in ``PARSERS``."""

import contextlib
from collections.abc import Callable

import pytest

from pyfect import _json_text, glob, semver_range
from pyfect import schema as S
from pyfect.encoding import ini, json5, jsonc, toml, yaml
from pyfect.exit import Failure
from pyfect.result import Ok

DEPTH = 200_000


PARSERS: dict[str, tuple[Callable[[str], object], str, str, tuple[type[Exception], ...]]] = {
    "json": (_json_text.parse, "[", "]", (ValueError,)),
    "json5": (json5.parse, "[", "]", ()),
    "jsonc": (jsonc.parse, "[", "]", ()),
    "toml array": (lambda t: toml.parse("a = " + t), "[", "]", ()),
    "toml inline table": (lambda t: toml.parse("a = " + t), "{b=", "}", ()),
    "yaml flow sequence": (yaml.parse, "[", "]", (ValueError,)),
    "yaml flow mapping": (yaml.parse, "{a: ", "}", (ValueError,)),
    "ini": (ini.parse, "[", "]", (TypeError,)),
    "glob": (glob.make, "{", "}", (ValueError,)),
    "semver range": (semver_range.parse, "(", ")", ()),
}


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_deep_input_is_read_or_rejected(name: str) -> None:
    parse, opening, closing, documented = PARSERS[name]
    with contextlib.suppress(*documented):
        parse(opening * DEPTH + closing * DEPTH)


def test_deep_yaml_blocks_are_read_or_rejected() -> None:
    with contextlib.suppress(ValueError):
        yaml.parse("".join(" " * depth + "- \n" for depth in range(20_000)))


def test_too_deep_json_for_a_schema_is_a_schema_error() -> None:
    exit = S.decode_unknown_exit(S.UnknownFromJsonString)("[" * DEPTH + "]" * DEPTH)
    assert isinstance(exit, Failure)
    error = exit.cause.find_error()
    assert isinstance(error, Ok) and isinstance(error.value, S.SchemaError)
