"""Regular expressions on untrusted text run in linear time: no pattern
splits one run of characters between two quantifiers (CPython's ``re``
backtracks through every split and holds the GIL while it does)."""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import pyfect
from pyfect import schema as S
from pyfect.ai import mcp_schema, mcp_server
from pyfect.encoding import yaml
from pyfect.http.middleware._compression import parse_accept_encoding
from pyfect.schema.getter._coerce import to_number

# A run of one character (then one that ends every pattern) is what makes an
# ambiguous pattern backtrack: each doubling of the run quadruples the time.
_RUN_CHARACTERS = "0 1aA-./\\\t\n,;:=%\"'_~#&+(<x"


def _seconds(call: Callable[[], object]) -> float:
    start = time.perf_counter()
    call()
    return time.perf_counter() - start


def _is_linear(call: Callable[[int], object], n: int = 4000) -> bool:
    """Doubling the input at most triples the time (a quadratic one is 4x),
    or the larger input takes under 5 ms either way."""
    small = min(_seconds(lambda: call(n)) for _ in range(3))
    large = min(_seconds(lambda: call(2 * n)) for _ in range(3))
    return large < 0.005 or large < 3 * small


def _module_patterns() -> Iterator[tuple[str, re.Pattern[str] | re.Pattern[bytes]]]:
    for info in pkgutil.walk_packages(pyfect.__path__, "pyfect."):
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            values: list[object] = [value]
            if isinstance(value, tuple | list):
                values = list(value)  # pyright: ignore[reportUnknownArgumentType]
            elif isinstance(value, dict):
                values = list(value.values())  # pyright: ignore[reportUnknownArgumentType]
            for item in values:
                if isinstance(item, re.Pattern):
                    yield f"{info.name}.{name}", item


def _anchored_cost(pattern: re.Pattern[str] | re.Pattern[bytes], n: int) -> None:
    for character in _RUN_CHARACTERS:
        text = character * n + "\x00"
        if isinstance(pattern.pattern, bytes):
            binary = text.encode("latin-1")
            pattern.fullmatch(binary)  # pyright: ignore[reportCallIssue, reportArgumentType]
            pattern.match(binary)  # pyright: ignore[reportCallIssue, reportArgumentType]
        else:
            pattern.fullmatch(text)  # pyright: ignore[reportCallIssue, reportArgumentType]
            pattern.match(text)  # pyright: ignore[reportCallIssue, reportArgumentType]


def test_every_module_pattern_matches_in_linear_time() -> None:
    """A guard over every compiled pattern pyfect keeps at module level, run
    as ``match``/``fullmatch`` against long runs of one character."""
    slow = [
        name
        for name, pattern in _module_patterns()
        if not _is_linear(lambda n, pattern=pattern: _anchored_cost(pattern, n), 1500)
    ]
    assert slow == []


def test_number_from_string_rejects_a_long_digit_run_in_linear_time() -> None:
    assert _is_linear(lambda n: to_number("1" * n + "x"))
    decode = S.decode_unknown_exit(S.FiniteFromString)
    assert _is_linear(lambda n: decode("1" * n + "x"))
    assert [to_number(text) for text in ("1.", ".5", "1e5", "1.5E-2", "0x1F", " 7 ")] == [
        1.0,
        0.5,
        100000.0,
        0.015,
        31.0,
        7.0,
    ]


_YAML_RUNS: list[Callable[[int], str]] = [
    lambda n: "a: " + "1" * n + "x",  # a plain scalar that looks like a float
    lambda n: "a: [b" + " " * n + "x]",  # flow folding
    lambda n: 'a: "b' + " " * n + 'x\n  c"',  # trailing blanks of a quoted line
    lambda n: 'a: "b' + "\\" * n + 'x\n  c"',  # escapes before the folded end
]


@pytest.mark.parametrize("make", _YAML_RUNS)
def test_yaml_parses_long_runs_in_linear_time(make: Callable[[int], str]) -> None:
    def parse(n: int) -> object:
        try:
            return yaml.parse(make(n))
        except ValueError:
            return None

    assert _is_linear(parse)


def test_a_resource_uri_template_matches_in_linear_time() -> None:
    template = mcp_server.uri_template(
        "x://", S.String, "-", S.String, "-", mcp_schema.param("c", S.String)
    )
    assert _seconds(lambda: template.match("x://" + "-" * 1500 + "/")) < 0.25
    assert template.match("x://a-b-c") == {"param0": "a", "param1": "b", "c": "c"}
    assert template.match("x://a-b") is None


def test_accept_encoding_parses_a_long_blank_run_in_linear_time() -> None:
    # The header is the client's: a run of blanks with no ``;`` after it.
    assert _is_linear(lambda n: parse_accept_encoding("gzip" + " " * n + "x"))
    assert parse_accept_encoding("gzip \t; \tq=0.5, br") == {"gzip": 0.5, "br": 1.0}


_SCANNING = frozenset({"search", "sub", "subn", "findall", "finditer", "split"})
# Scanning uses on text pyfect's own process or its user wrote.
_TRUSTED_SCANS = frozenset(
    {
        "pyfect/_stack_frame.py:_LOCATION",  # a traceback's frame lines
        "pyfect/config_provider/_dotenv.py:_LINE",  # the app's .env file
        "pyfect/persistence/user_directories.py:[\\\\/]+$",  # an environment path
        "pyfect/persistence/user_directories.py:/+$",
    }
)


def _scanning_patterns() -> Iterator[tuple[str, re.Pattern[str] | re.Pattern[bytes]]]:
    """Every pattern pyfect applies with a scanning method: a module-level
    one (``_NAME.sub(...)``) or a literal (``re.sub("...", ...)``)."""
    root = Path(pyfect.__file__).parent
    for file in sorted(root.rglob("*.py")):
        relative = file.relative_to(root.parent)
        module_name = ".".join(relative.with_suffix("").parts).removesuffix(".__init__")
        for node in ast.walk(ast.parse(file.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SCANNING
                and isinstance(node.func.value, ast.Name)
            ):
                continue
            name = node.func.value.id
            first = node.args[0] if node.args else None
            if name == "re" and isinstance(first, ast.Constant) and isinstance(first.value, str):
                yield f"{relative.as_posix()}:{first.value}", re.compile(first.value)
                continue
            pattern = getattr(importlib.import_module(module_name), name, None)
            if isinstance(pattern, re.Pattern):
                yield f"{relative.as_posix()}:{name}", pattern


def _scanning_cost(pattern: re.Pattern[str] | re.Pattern[bytes], n: int) -> None:
    for character in _RUN_CHARACTERS:
        text = character * n + "\x00"
        if isinstance(pattern.pattern, bytes):
            pattern.search(text.encode("latin-1"))  # pyright: ignore[reportCallIssue, reportArgumentType]
        else:
            pattern.search(text)  # pyright: ignore[reportCallIssue, reportArgumentType]


def test_every_scanning_pattern_runs_in_linear_time() -> None:
    """A guard: ``search``, ``sub``, ``split``... try the pattern at every
    position, so one that backtracks over a run is quadratic even when
    ``match`` is linear (``[ \\t]*;`` over a header's blanks)."""
    found = dict(_scanning_patterns())
    assert "pyfect/http/_foreign_path.py:_ENCODED_SLASH" in found
    slow = [
        name
        for name, pattern in found.items()
        if name not in _TRUSTED_SCANS
        and not _is_linear(lambda n, pattern=pattern: _scanning_cost(pattern, n), 1500)
    ]
    assert slow == []
    assert found.keys() >= _TRUSTED_SCANS
