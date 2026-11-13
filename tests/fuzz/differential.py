"""pyfect's parsers against Effect's (effect_oracle.ts, under Node) on the same text.

``answers`` computes what effect_oracle.ts computes, in the same JSON form, so an
input where they differ is a divergence from Effect. ``effect_answers.json``
holds Node's answers for the checked-in corpus (test_differential.py compares
them); ``python -m fuzz --differential DIR...`` compares on any corpus, such as
one a long Atheris run grew, and prints the differences.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pyfect import (
    _json_text,
    big_decimal,
    byte_size,
    cron,
    duration,
    glob,
    json_pointer,
    semver,
    semver_range,
)
from pyfect import date_time as DateTime
from pyfect import schema as S
from pyfect._binary_codecs import base64_decode, base64_url_decode, hex_decode
from pyfect.encoding import ini, json5, jsonc, toml, yaml
from pyfect.http import cookies
from pyfect.result import Ok, Result

ORACLE = Path(__file__).with_name("effect_oracle.ts")
ANSWERS = Path(__file__).with_name("effect_answers.json")
_START = datetime(2024, 3, 10, 1, 30, tzinfo=UTC)
_SAFE = 2**53

type Answer = object


def _date(value: object) -> object:
    """A ``Date``'s ``toJSON``: a TOML offset date-time is one in Effect."""
    if isinstance(value, datetime):
        utc = value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"
    raise TypeError(f"{type(value).__name__} has no JSON form")


def _as_js_numbers(value: object) -> object:
    """Ints past 2**53 as JavaScript's nearest ``Number``: pyfect's parsers keep
    them whole, a documented difference from Effect."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) > _SAFE:
        return float(value)
    if isinstance(value, dict):
        items = cast("dict[object, object]", value).items()
        return {key: _as_js_numbers(item) for key, item in items}
    if isinstance(value, list):
        return [_as_js_numbers(item) for item in cast("list[object]", value)]
    return value


def _json(value: object) -> object:
    """The value as the oracle's ``JSON.parse(JSON.stringify(value))``: objects
    compare without their key order (JavaScript lists integer keys first)."""
    text = _json_text.stringify(_as_js_numbers(value), default=_date)
    return json.loads(text)


def _ok[A](result: Result[A, object], f: Callable[[A], Answer]) -> Answer:
    return f(result.value) if isinstance(result, Ok) else None


def _raises(f: Callable[[], Answer]) -> Answer:
    try:
        return f()
    except (ValueError, TypeError):
        return None


def _nanos(found: duration.Duration | None) -> Answer:
    if found is None:
        return None
    nanos = duration.to_nanos(found)
    return "infinity" if nanos is None else str(nanos)


def _cron(text: str) -> Answer:
    def run(found: cron.Cron) -> Answer:
        upcoming = _raises(lambda: round(cron.next(found, _START).timestamp() * 1000))
        return [cron.format(found), upcoming]

    return _ok(cron.parse(text), run)


def _glob(text: str) -> Answer:
    pattern, _, path = text.partition("\n")
    return _raises(lambda: glob.match(glob.make(pattern), path))


def _zone(text: str) -> Answer:
    zone = DateTime.zone_from_string(text)
    return None if zone is None else DateTime.zone_to_string(zone)


def _zoned(text: str) -> Answer:
    zoned = DateTime.make_zoned_from_string(text)
    return None if zoned is None else DateTime.format_iso_zoned(zoned)


def _json_string(text: str) -> Answer:
    """``UnknownFromJsonString`` decoded then encoded, the text read back (in
    a list, so a ``null`` document is no rejection): what Effect's
    ``JSON.stringify`` writes for the value its ``JSON.parse`` read, an
    infinity as ``null``."""
    schema = S.UnknownFromJsonString
    decoded = S.decode_unknown_result(schema)(text)
    if not isinstance(decoded, Ok):
        return None
    return _ok(
        S.encode_unknown_result(schema)(decoded.value), lambda t: [_json(_json_text.parse(t))]
    )


ANSWERS_OF: dict[str, Callable[[str], Answer]] = {
    "base64": lambda t: _ok(base64_decode(t), bytes.hex),
    "base64url": lambda t: _ok(base64_url_decode(t), bytes.hex),
    "hex": lambda t: _ok(hex_decode(t), bytes.hex),
    "json5": lambda t: _ok(json5.parse(t), _json),
    "jsonc": lambda t: _ok(jsonc.parse(t), _json),
    "toml": lambda t: _ok(toml.parse(t), _json),
    "yaml": lambda t: _raises(lambda: _json(yaml.parse(t))),
    "ini": lambda t: _raises(lambda: _json(ini.parse(t))),
    "duration": lambda t: _nanos(duration.from_input(t)),
    "duration_iso": lambda t: _nanos(duration.from_iso(t)),
    "cron": _cron,
    "semver": lambda t: _ok(semver.parse(t), str),
    "semver_range": lambda t: _ok(semver_range.parse(t), str),
    "big_decimal": lambda t: None if (d := big_decimal.from_string(t)) is None else d.format(),
    "byte_size": lambda t: None if (b := byte_size.from_string(t)) is None else str(b),
    "zone": _zone,
    "zoned": _zoned,
    "glob": _glob,
    "pointer": json_pointer.parse_uri_fragment,
    "cookies": cookies.parse_header,
    "json_string": _json_string,
}

# Which parsers each fuzz target's inputs go to, and how a target reads its bytes.
PARSERS_OF: dict[str, tuple[str, ...]] = {
    "base64_hex": ("base64", "base64url", "hex"),
    "json5": ("json5", "jsonc"),
    "duration": ("duration", "duration_iso"),
    "cron": ("cron",),
    "versions": ("semver", "semver_range"),
    "numbers": ("big_decimal", "byte_size"),
    "date_time": ("zone", "zoned"),
    "schema_json": ("json_string",),
}


def inputs_of(target: str, data: bytes) -> list[tuple[str, str]]:
    """The ``(parser, text)`` pairs ``target``'s input ``data`` feeds."""
    text = data.decode("utf-8", "surrogateescape")
    if target == "toml_yaml_ini" and data:
        parser = ("toml", "yaml", "ini")[data[0] % 3]
        return [(parser, data[1:].decode("utf-8", "surrogateescape"))]
    if target == "pointer_glob":
        path, _, pattern = text.partition("\n")
        return [("pointer", path), ("glob", f"{pattern}\n{path}")]
    if target == "http_text" and data and data[0] % 8 == 0:
        return [("cookies", data[1:].decode("latin-1"))]
    return [(parser, text) for parser in PARSERS_OF.get(target, ())]


@contextmanager
def _in_utc() -> Generator[None]:
    """Local time as UTC, as the oracle runs: legacy date strings (``+0530``)
    are local times, in JavaScript and in pyfect."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = previous
        time.tzset()


def pyfect_answers(inputs: Iterable[tuple[str, str]]) -> list[Answer]:
    with _in_utc():
        return [ANSWERS_OF[parser](text) for parser, text in inputs]


def effect_answers(inputs: list[tuple[str, str]]) -> list[Answer]:
    """Effect's answers, from Node; needs ``PYFECT_EFFECT_REF``."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as file:
        json.dump(inputs, file)
    try:
        out = subprocess.run(
            ["node", str(ORACLE), file.name],
            capture_output=True,
            text=True,
            check=True,
            # A zoneless cron runs in the zone of the time it starts from: a JavaScript
            # ``Date`` has none, so Node takes the machine's; pyfect's start is in UTC.
            env={**os.environ, "TZ": "UTC"},
        ).stdout
    finally:
        os.unlink(file.name)
    answers: list[Answer] = json.loads(out)
    return answers


_DAY_OR_MORE = re.compile(r"[+-](?:2[4-9]|[3-9][0-9]):?[0-9]{2}$")


def _python_cannot_hold(parser: str, text: str, mine: Answer) -> bool:
    """The one documented difference: a zone offset of a day or more, which
    Effect accepts and Python's ``tzinfo`` cannot hold (``zone_from_string``)."""
    return parser in ("zone", "zoned") and mine is None and bool(_DAY_OR_MORE.search(text))


def differences(
    inputs: list[tuple[str, str]], theirs: list[Answer]
) -> list[tuple[str, str, Answer, Answer]]:
    ours = pyfect_answers(inputs)
    return [
        (parser, text, mine, effect)
        for (parser, text), mine, effect in zip(inputs, ours, theirs, strict=True)
        if mine != effect and not _python_cannot_hold(parser, text, mine)
    ]


def corpus_inputs(folders: Iterable[tuple[str, Path]]) -> list[tuple[str, str]]:
    """The distinct ``(parser, text)`` pairs of the corpus inputs in ``folders``
    (``(target, folder)``), sorted."""
    inputs: set[tuple[str, str]] = set()
    for name, folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            try:
                data = path.read_bytes()
            except FileNotFoundError:  # a running fuzzer replaced it
                continue
            inputs.update(inputs_of(name, data))
    return sorted(inputs)


def write_answers(inputs: list[tuple[str, str]]) -> None:
    """Effect's answers for ``inputs``, saved as ``effect_answers.json``."""
    answers = effect_answers(inputs)
    rows = [[parser, text, answer] for (parser, text), answer in zip(inputs, answers, strict=True)]
    ANSWERS.write_text(json.dumps(rows, indent=0) + "\n", encoding="utf-8")
