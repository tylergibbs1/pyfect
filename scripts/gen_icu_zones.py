"""Generate ``src/pyfect/date_time/_icu_zones.py``, the zone ids Node's ICU
accepts and the canonical id it gives each:
``uv run python scripts/gen_icu_zones.py [ZONEINFO64]``.

Effect's ``zoneMakeNamed`` names a zone by what
``new Intl.DateTimeFormat("en-US", {timeZone}).resolvedOptions().timeZone``
gives: ICU's canonical id, which runs links backwards to old names
(``Asia/Kolkata`` is ``Asia/Calcutta``, ``EST`` is ``America/Panama``). The
ids asked about are every one ICU's ``zoneinfo64`` lists (its tz data for
Node's ``process.versions.tz``, from unicode-org/icu-data, or the file given),
every one ``zoneinfo`` knows, and ``Intl.supportedValuesOf("timeZone")``; each
is resolved by the ``node`` on ``PATH``, whose version and ICU version the
generated module records. ``zoneinfo64`` also says which zone's data ICU uses
for an id that is a link, so an id ``zoneinfo`` lacks can load that zone's;
an id with its own data that ``zoneinfo`` doesn't know at all (the
``SystemV/*`` zones tz dropped in 2020b) gets ICU's data as TZif bytes.
"""

from __future__ import annotations

import base64
import calendar
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

_TARGET = Path(__file__).parent.parent / "src" / "pyfect" / "date_time" / "_icu_zones.py"
_ZONE = re.compile(r"^  /\* (\S+) \*/ :(?:int \{ (\d+) \}|table \{\n(.*?)\n  \})", re.M | re.S)
_FIELD = re.compile(r'^    (\w+):?(\w*) \{ "?(.*?)"? \}$', re.MULTILINE)
_RULE = re.compile(r"^  (\w+):intvector \{\n\s+(.*?)\n  \}", re.MULTILINE)

_RESOLVE = """
const ids = JSON.parse(require("fs").readFileSync(0, "utf8"))
const canonical = {}
for (const id of ids) {
  try {
    canonical[id] = new Intl.DateTimeFormat("en-US", { timeZone: id }).resolvedOptions().timeZone
  } catch {}
}
process.stdout.write(JSON.stringify({
  node: process.versions.node,
  icu: process.versions.icu,
  tz: process.versions.tz,
  supported: Intl.supportedValuesOf("timeZone"),
  canonical,
}))
"""


def _node(script: str, stdin: str = "") -> str:
    return subprocess.run(
        ["node", "-e", script], input=stdin, capture_output=True, text=True, check=True
    ).stdout


def _zoneinfo64(argv: list[str]) -> str:
    if argv:
        return Path(argv[0]).read_text()
    tz = _node("process.stdout.write(process.versions.tz)")
    url = f"repos/unicode-org/icu-data/contents/tzdata/icunew/{tz}/44/zoneinfo64.txt"
    return subprocess.run(
        ["gh", "api", url, "-H", "Accept: application/vnd.github.raw"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _icu_zones(text: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Every id ``zoneinfo64`` lists with the id whose data it uses, and the
    fields of each id that has its own data."""
    zones = _ZONE.findall(text)
    names = [name for name, _index, _body in zones]
    links = {name: names[int(index)] if index else name for name, index, _body in zones}
    tables = {
        name: {field: value for field, _kind, value in _FIELD.findall(body)}
        for name, index, body in zones
        if not index
    }
    return links, tables


def _ints(text: str) -> list[int]:
    return [int(part) for part in text.split(",")]


def _designation(offset: int) -> str:
    sign = "-" if offset < 0 else "+"
    hours, rest = divmod(abs(offset), 3600)
    return f"{sign}{hours:02}" + (f"{rest // 60:02}" if rest else "")


def _posix_offset(offset: int) -> str:
    hours, rest = divmod(abs(offset), 3600)
    text = ("" if offset <= 0 else "-") + str(hours)
    return text + (f":{rest // 60:02}" if rest else "")


def _posix_date(month: int, day: int, weekday: int, time: int, mode: int) -> str:
    """An ICU ``SimpleTimeZone`` rule date as a POSIX ``Mm.w.d/time``: only
    "the last weekday on or before the month's last day", in wall time."""
    last = calendar.monthrange(2001, month + 1)[1]
    if not (weekday < 0 and day == -last and mode == 0 and time % 3600 == 0):
        raise ValueError(f"unsupported ICU rule date {(month, day, weekday, time, mode)}")
    return f"M{month + 1}.5.{-weekday - 1}/{time // 3600}"


def _tzif(fields: dict[str, str], rules: dict[str, list[int]]) -> bytes:
    """TZif (version 2) bytes for one ``zoneinfo64`` table."""
    if set(fields) - {"trans", "typeOffsets", "typeMap", "finalRule", "finalRaw", "finalYear"}:
        raise ValueError(f"unsupported zoneinfo64 fields {sorted(fields)}")
    pairs = _ints(fields["typeOffsets"])
    types = [(raw + dst, dst != 0) for raw, dst in zip(pairs[::2], pairs[1::2], strict=True)]
    times = _ints(fields["trans"]) if "trans" in fields else []
    indexes = list(bytes.fromhex(fields.get("typeMap", "")))
    names = list(dict.fromkeys(_designation(offset) for offset, _dst in types))
    chars = b"".join(name.encode() + b"\0" for name in names)
    footer = f"<{_designation(types[0][0])}>{_posix_offset(types[0][0])}"
    if "finalRule" in fields:
        rule = rules[fields["finalRule"]]
        raw, savings = int(fields["finalRaw"]), rule[10]
        footer = (
            f"<{_designation(raw)}>{_posix_offset(raw)}"
            f"<{_designation(raw + savings)}>{_posix_offset(raw + savings)}"
            f",{_posix_date(*rule[0:5])},{_posix_date(*rule[5:10])}"
        )
    body = b"".join(struct.pack(">q", time) for time in times) + bytes(indexes)
    for offset, dst in types:
        index = sum(len(name) + 1 for name in names[: names.index(_designation(offset))])
        body += struct.pack(">lBB", offset, dst, index)
    counts = struct.pack(">6l", 0, 0, 0, len(times), len(types), len(chars))
    empty = b"TZif2" + bytes(15) + struct.pack(">6l", 0, 0, 0, 0, 1, 1) + bytes(6) + b"\0"
    return empty + b"TZif2" + bytes(15) + counts + body + chars + f"\n{footer}\n".encode()


def _base64_entry(key: str, data: bytes) -> list[str]:
    text = base64.b64encode(data).decode()
    chunks = [text[i : i + 88] for i in range(0, len(text), 88)]
    return [f"    {json.dumps(key)}: (", *(f'        "{chunk}"' for chunk in chunks), "    ),"]


def _module(found: dict[str, Any], data: dict[str, str], tzif: dict[str, bytes]) -> str:
    canonical: dict[str, str] = found["canonical"]
    lines = [
        f'"""ICU\'s canonical zone ids as Node {found["node"]} (ICU {found["icu"]}, tz'
        f" {found['tz']}) gives",
        'them. Generated by scripts/gen_icu_zones.py; do not edit."""',
        "",
        "from typing import Final",
        "",
        f'NODE_VERSION: Final = "{found["node"]}"',
        f'ICU_VERSION: Final = "{found["icu"]}"',
        f'TZ_VERSION: Final = "{found["tz"]}"',
        "",
        "CANONICAL: Final[dict[str, str]] = {",
        *(f"    {json.dumps(k)}: {json.dumps(v)}," for k, v in sorted(canonical.items())),
        "}",
        '"""Every id Node accepts (as ICU spells it), with its canonical id."""',
        "",
        "DATA: Final[dict[str, str]] = {",
        *(f"    {json.dumps(k)}: {json.dumps(v)}," for k, v in sorted(data.items())),
        "}",
        '"""The zone whose data ICU uses for a canonical id that is a link."""',
        "",
        "TZIF: Final[dict[str, str]] = {",
        *(line for k, v in sorted(tzif.items()) for line in _base64_entry(k, v)),
        "}",
        '"""ICU\'s own data, as base64 TZif, for the canonical ids no tz zone has."""',
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    text = _zoneinfo64(argv)
    links, tables = _icu_zones(text)
    rules = {name: _ints(values) for name, values in _RULE.findall(text)}
    supported: list[str] = json.loads(
        _node('process.stdout.write(JSON.stringify(Intl.supportedValuesOf("timeZone")))')
    )
    ids = sorted({*links, *available_timezones(), *supported})
    found = json.loads(_node(_RESOLVE, json.dumps(ids)))
    canonical: dict[str, str] = found["canonical"]
    data = {
        zone: links[zone]
        for zone in sorted(set(canonical.values()))
        if zone in links and links[zone] != zone
    }
    known = available_timezones()
    tzif = {
        zone: _tzif(tables[zone], rules)
        for zone in sorted(set(canonical.values()))
        if zone in tables and zone not in known
    }
    _TARGET.write_text(_module(found, data, tzif))
    print(f"{len(canonical)} ids, {len(set(canonical.values()))} canonical, written to {_TARGET}")


if __name__ == "__main__":
    main(sys.argv[1:])
