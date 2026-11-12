"""Generate ``src/pyfect/date_time/_intl/cldr.zip``, the CLDR data
``date_time.intl`` formats with: ``uv run python scripts/gen_intl_cldr.py``.

Effect's ``DateTime.format`` is ``Intl.DateTimeFormat``, which Node runs on
ICU. ICU does not read CLDR itself: its release carries CLDR converted to its
own resource bundles (``icu4c-<ICU>-data.zip``), with ICU's aliases and
fallbacks, and that converted data is what Node formats with. So the data here
is ICU's, for the ICU of the ``node`` on ``PATH``, read the way ICU reads it
(locale fallback, ``%%Parent``, ``/LOCALE/`` aliases, a calendar missing a
resource falling back to Gregorian) and stored per locale as the difference
from its parent. Which metazone a zone is in, and when, is ICU's table for
Node's tz release (``metaZones.txt`` from ICU's tz update): ICU ships it with
each tz update, ahead of CLDR's, and it starts every zone at 1970, so there are
no metazone names before then. CLDR's own JSON (``cldr-core``, the release
Node's ICU is built from) gives the supplemental data: likely subtags, hour
cycles, calendar preferences, day period rules and digits.

Downloads go to a folder given as the argument (kept for the next run), else a
temporary one. The archive records Node's, ICU's, CLDR's and tz's versions;
ICU's ``LICENSE`` (the Unicode License v3 the data is under) is written beside
it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

_TARGET = Path(__file__).parent.parent / "src" / "pyfect" / "date_time" / "_intl" / "cldr.zip"
# ICU's data is CLDR's, under the Unicode License v3: the license ships with it.
_LICENSE = _TARGET.with_name("LICENSE")
_CALENDARS = ["gregorian", "buddhist", "persian"]
_STYLES = ["full", "long", "medium", "short"]
_FIELDS = [
    *("era", "year", "quarter", "month", "week", "weekOfMonth", "weekday", "dayOfYear"),
    *("weekdayOfMonth", "day", "dayperiod", "hour", "minute", "second", "zone"),
]
_NO_INHERITANCE = "\u2205\u2205\u2205"
_WIDTHS = {"abbreviated": "AmPmMarkersAbbr", "wide": "AmPmMarkers", "narrow": "AmPmMarkersNarrow"}

_NODE = """
const tags = JSON.parse(require("fs").readFileSync(0, "utf8"))
process.stdout.write(JSON.stringify({
  node: process.versions.node,
  icu: process.versions.icu,
  cldr: process.versions.cldr,
  tz: process.versions.tz,
  available: tags.filter((tag) => {
    try {
      return Intl.DateTimeFormat.supportedLocalesOf([tag]).length === 1
        && new Intl.DateTimeFormat(tag).resolvedOptions().locale === tag
    } catch { return false }
  }),
}))
"""


def _fetch(url: str, path: Path) -> Path:
    if not path.exists():
        with urllib.request.urlopen(url) as response:
            path.write_bytes(response.read())
    return path


def _icu_data(folder: Path, icu: str) -> zipfile.ZipFile:
    url = f"https://github.com/unicode-org/icu/releases/download/release-{icu}/icu4c-{icu}-data.zip"
    return zipfile.ZipFile(_fetch(url, folder / f"icu4c-{icu}-data.zip"))


def _cldr_core(folder: Path, cldr: str) -> dict[str, Any]:
    version = f"{cldr.removesuffix('.0')}.0.0" if cldr.count(".") < 2 else cldr
    url = f"https://registry.npmjs.org/cldr-core/-/cldr-core-{version}.tgz"
    path = _fetch(url, folder / f"cldr-core-{version}.tgz")
    found: dict[str, Any] = {}
    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.endswith(".json"):
                source = archive.extractfile(member)
                assert source is not None
                found[member.name.split("/", 1)[1]] = json.loads(source.read())
    return found


# ICU's resource bundle text format.


@dataclass(frozen=True, slots=True)
class _Alias:
    path: str


type _Value = str | _Alias | list[_Value] | dict[str, _Value]
"""A resource: a string, an alias, an array or a table."""


_TOKEN = re.compile(
    r'\s+|//[^\n]*|/\*.*?\*/|(?P<string>"(?:[^"\\]|\\.)*")|(?P<punct>[{},:])|(?P<word>[^\s{},:"]+)',
    re.DOTALL,
)
_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|x[0-9a-fA-F]{2}|.)")


def _unescape(text: str) -> str:
    def one(match: re.Match[str]) -> str:
        code = match.group(1)
        if code[0] in "uUx" and len(code) > 1:
            return chr(int(code[1:], 16))
        return {"n": "\n", "t": "\t", "r": "\r"}.get(code, code)

    return _ESCAPE.sub(one, text[1:-1])


def _tokens(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for match in _TOKEN.finditer(text.lstrip("﻿")):
        kind = match.lastgroup
        if kind == "string":
            found.append(("s", _unescape(match.group())))
        elif kind == "punct":
            found.append(("p", match.group()))
        elif kind == "word":
            found.append(("w", match.group()))
    return found


def _parse_bundle(text: str) -> tuple[str, dict[str, _Value]]:
    tokens = _tokens(text)
    index = 0

    def body(kind: str) -> _Value:
        """The value after ``{``, up to and with its ``}``."""
        nonlocal index
        table: dict[str, _Value] = {}
        items: list[_Value] = []
        commas = False
        while True:
            token_kind, value = tokens[index]
            if token_kind == "p" and value == "}":
                index += 1
                break
            if token_kind == "p" and value == ",":
                commas = True
                index += 1
                continue
            if token_kind == "p" and value == "{":
                index += 1
                items.append(body(""))
                continue
            following = tokens[index + 1]
            if following[0] == "p" and following[1] in "{:":
                key = value
                index += 1
                child_kind = ""
                if tokens[index][1] == ":":
                    child_kind = tokens[index + 1][1]
                    index += 2
                assert tokens[index][1] == "{", (key, tokens[index])
                index += 1
                table[key] = body(child_kind)
                continue
            # A string; adjacent strings are one.
            last = items[-1] if items else None
            if isinstance(last, str) and not commas and token_kind == "s":
                items[-1] = last + value
            else:
                items.append(value)
            index += 1
        if kind == "alias":
            return _Alias(_string(items[0]))
        if table:
            return table
        if len(items) == 1 and not commas and kind not in ("array", "intvector"):
            return items[0]
        return items if items or kind else {}

    name = tokens[0][1]
    index = 1
    if tokens[index][1] == ":":
        index += 2
    index += 1
    root = body("table")
    return name, root if isinstance(root, dict) else {}


class _Tree:
    """One ICU data tree (``locales``, ``zone``), read with ICU's fallback."""

    def __init__(self, archive: zipfile.ZipFile, tree: str) -> None:
        self._bundles: dict[str, dict[str, _Value]] = {}
        prefix = f"data/{tree}/"
        for name in archive.namelist():
            if name.startswith(prefix) and name.endswith(".txt") and "/" not in name[len(prefix) :]:
                locale = name[len(prefix) : -4]
                self._bundles[locale] = _parse_bundle(archive.read(name).decode("utf-8"))[1]

    def names(self) -> list[str]:
        return sorted(self._bundles)

    def has(self, locale: str) -> bool:
        return locale in self._bundles

    def alias_of(self, locale: str) -> str | None:
        found = self._bundles.get(locale, {}).get("%%ALIAS")
        return found if isinstance(found, str) else None

    def parent(self, locale: str) -> str | None:
        if locale == "root":
            return None
        explicit = self._bundles.get(locale, {}).get("%%Parent")
        if isinstance(explicit, str):
            return explicit
        return locale.rsplit("_", 1)[0] if "_" in locale else "root"

    def chain(self, locale: str) -> list[str]:
        found: list[str] = []
        current: str | None = locale
        while current is not None:
            if current in self._bundles:
                found.append(current)
            current = self.parent(current)
        return found

    def _follow(self, alias: _Alias, requested: str, rest: list[str]) -> _Value | None:
        first, _, path = alias.path.lstrip("/").partition("/")
        locale = requested if first == "LOCALE" else first
        return self.get(locale, [*path.split("/"), *rest])

    def _walk(self, node: _Value, path: list[str], requested: str) -> _Value | None:
        for depth, key in enumerate(path):
            if isinstance(node, _Alias):
                return self._follow(node, requested, path[depth:])
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        if isinstance(node, _Alias):
            return self._follow(node, requested, [])
        return node

    def get(self, locale: str, path: list[str]) -> _Value | None:
        """``ures_getByKeyWithFallback``: the first bundle in the chain with ``path``."""
        for level in self.chain(locale):
            found = self._walk(self._bundles[level], path, locale)
            if found is not None:
                return found
        return None

    def items(self, locale: str, path: list[str]) -> list[tuple[str, _Value]]:
        """``ures_getAllItemsWithFallback`` over a table: the locale's keys first
        (sorted, as ICU stores them), then each parent's not yet seen; an alias
        on the way continues with its target's."""
        found: list[tuple[str, _Value]] = []
        seen: set[str] = set()

        def add(pairs: list[tuple[str, _Value]]) -> None:
            for key, value in pairs:
                if key not in seen:
                    seen.add(key)
                    found.append((key, value))

        for level in self.chain(locale):
            node: _Value | None = self._bundles[level]
            for depth, key in enumerate(path):
                node = node.get(key) if isinstance(node, dict) else None
                if isinstance(node, _Alias):
                    first, _, target = node.path.lstrip("/").partition("/")
                    origin = locale if first == "LOCALE" else first
                    add(self.items(origin, [*target.split("/"), *path[depth + 1 :]]))
                    return found
            if isinstance(node, dict):
                add([(key, node[key]) for key in sorted(node, key=lambda k: k.encode("utf-8"))])
        return found

    def own(self, level: str, path: list[str]) -> _Value | None:
        """``path`` in the bundle ``level`` alone."""
        node: _Value = self._bundles[level]
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node


# What formatting reads from a locale.


def _list(value: _Value) -> list[_Value]:
    return value if isinstance(value, list) else [value]


def _string(value: _Value | None) -> str:
    while isinstance(value, list):
        value = value[0] if value else ""
    return value if isinstance(value, str) else ""


def _calendar_get(tree: _Tree, locale: str, calendar: str, path: list[str]) -> _Value | None:
    found = tree.get(locale, ["calendar", calendar, *path])
    if found is None and calendar != "gregorian":
        found = tree.get(locale, ["calendar", "gregorian", *path])
    return found


def _calendar_items(
    tree: _Tree, locale: str, calendar: str, path: list[str]
) -> list[tuple[str, _Value]]:
    found = tree.items(locale, ["calendar", calendar, *path])
    if not found and calendar != "gregorian":
        found = tree.items(locale, ["calendar", "gregorian", *path])
    return found


def _names(
    tree: _Tree, locale: str, calendar: str, table: str, widths: list[str]
) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for context in ("format", "stand-alone"):
        found[context] = {}
        for width in widths:
            names = _calendar_get(tree, locale, calendar, [table, context, width])
            if isinstance(names, list):
                found[context][width] = [_string(name) for name in names]
    return found


def _calendar(tree: _Tree, locale: str, calendar: str) -> dict[str, Any]:
    patterns = _list(_calendar_get(tree, locale, calendar, ["DateTimePatterns"]) or [])
    at_time = _calendar_get(tree, locale, calendar, ["DateTimePatterns%atTime"])
    periods: dict[str, dict[str, str]] = {}
    for width, markers_key in _WIDTHS.items():
        table = _calendar_get(tree, locale, calendar, ["dayPeriod", "format", width])
        periods[width] = (
            {k: _string(v) for k, v in table.items() if not k.endswith("%variant")}
            if isinstance(table, dict)
            else {}
        )
        markers = _calendar_get(tree, locale, calendar, [markers_key])
        if isinstance(markers, list) and len(markers) >= 2:
            periods[width]["am"], periods[width]["pm"] = _string(markers[0]), _string(markers[1])
    eras: dict[str, list[str]] = {}
    for width in ("abbreviated", "wide", "narrow"):
        names = _calendar_get(tree, locale, calendar, ["eras", width])
        if isinstance(names, list):
            eras[width] = [_string(name) for name in names]
        elif isinstance(names, dict):
            numbered = {int(k): _string(v) for k, v in names.items() if k.isdigit()}
            eras[width] = [numbered.get(i, "") for i in range(max(numbered, default=-1) + 1)]
    return {
        "months": _names(tree, locale, calendar, "monthNames", ["abbreviated", "wide", "narrow"]),
        "days": _names(
            tree, locale, calendar, "dayNames", ["abbreviated", "wide", "narrow", "short"]
        ),
        "dayPeriods": {"format": periods},
        "eras": eras,
        "timeFormats": [_string(patterns[i]) for i in range(4)],
        "dateFormats": [_string(patterns[i]) for i in range(4, 8)],
        "dateTimeFormats": [_string(patterns[i]) for i in range(9, 13)],
        "atTime": [_string(p) for p in at_time] if isinstance(at_time, list) else ["", "", "", ""],
        "availableFormats": [
            [key, _string(value)]
            for key, value in _calendar_items(tree, locale, calendar, ["availableFormats"])
        ],
        "appendItems": {
            key: _string(value)
            for key, value in _calendar_items(tree, locale, calendar, ["appendItems"])
        },
    }


def _zone_names(tree: _Tree, locale: str) -> dict[str, Any]:
    zones: dict[str, Any] = {}
    metazones: dict[str, Any] = {}
    formats: dict[str, str] = {}
    widths = {"l": "long", "s": "short"}
    kinds = {"s": "standard", "d": "daylight"}
    for key, value in tree.items(locale, ["zoneStrings"]):
        if key in ("gmtFormat", "hourFormat", "gmtZeroFormat"):
            formats[key] = _string(value)
            continue
        if not isinstance(value, dict):
            continue
        names: dict[str, dict[str, str]] = {}
        for level in tree.chain(locale):
            own = tree.own(level, ["zoneStrings", key])
            if not isinstance(own, dict):
                continue
            for code, text in own.items():
                if len(code) == 2 and code[0] in widths and code[1] in kinds:
                    # ICU's no-inheritance marker: no name, and none from a parent.
                    name = "" if _string(text) == _NO_INHERITANCE else _string(text)
                    names.setdefault(widths[code[0]], {}).setdefault(kinds[code[1]], name)
        if not names:
            continue
        if key.startswith("meta:"):
            metazones[key[5:]] = names
        else:
            zones[key.replace(":", "/")] = names
    return {"zoneFormats": formats, "zones": zones, "metazones": metazones}


def _minus_signs(locales: _Tree, locale: str, systems: list[str]) -> dict[str, str]:
    """Each numbering system's minus sign, else Latin digits' (as ICU's
    ``DecimalFormatSymbols``)."""
    found: dict[str, str] = {}
    for system in systems:
        for source in (system, "latn"):
            sign = locales.get(locale, ["NumberElements", source, "symbols", "minusSign"])
            if isinstance(sign, str):
                found[system] = sign
                break
    return found


def _locale(locales: _Tree, zones: _Tree, locale: str, systems: list[str]) -> dict[str, Any]:
    numbering = locales.get(locale, ["NumberElements", "default"])
    return {
        "minusSigns": _minus_signs(locales, locale, systems),
        "calendars": {calendar: _calendar(locales, locale, calendar) for calendar in _CALENDARS},
        "fields": {
            name: _string(locales.get(locale, ["fields", name, "dn"]))
            for name in _FIELDS
            if locales.get(locale, ["fields", name, "dn"]) is not None
        },
        **_zone_names(zones, locale),
        "numberingSystem": numbering if isinstance(numbering, str) else "latn",
    }


def _diff(child: object, parent: object) -> object:
    """``child`` as changes to ``parent``: changed keys, ``None`` for removed ones."""
    if not isinstance(child, dict) or not isinstance(parent, dict):
        return cast("object", child)
    child = cast("dict[str, object]", child)
    parent = cast("dict[str, object]", parent)
    found: dict[str, object] = {}
    for key, value in child.items():
        if key not in parent:
            found[key] = value
        elif value != parent[key]:
            found[key] = _diff(value, parent[key])
    for key in parent:
        if key not in child:
            found[key] = None
    return found


_ALWAYS = ["1970-01-01 00:00", "9999-12-31 23:59"]


def _icu_metazones(folder: Path, tz: str) -> dict[str, list[list[str]]]:
    """ICU's ``metazoneInfo`` for tz ``tz``: per zone, ``[metazone, from, to]`` (UTC)."""
    url = f"https://raw.githubusercontent.com/unicode-org/icu-data/main/tzdata/icunew/{tz}/44/metaZones.txt"
    _, data = _parse_bundle(_fetch(url, folder / f"metaZones-{tz}.txt").read_text("utf-8"))
    found: dict[str, list[list[str]]] = {}
    info = data["metazoneInfo"]
    assert isinstance(info, dict)
    for zone, uses in info.items():
        entries = uses if isinstance(uses, list) else [uses]
        found[zone.replace(":", "/")] = [
            [entry, *_ALWAYS]
            if isinstance(entry, str)
            else [*map(_string, _list(entry)), *_ALWAYS[len(_list(entry)) - 1 :]][:3]
            for entry in entries
        ]
    return found


def _supplemental(core: dict[str, Any]) -> dict[str, Any]:
    def read(name: str) -> Any:
        return core[f"supplemental/{name}.json"]["supplemental"]

    aliases = read("aliases")["metadata"]["alias"]
    return {
        "likely": read("likelySubtags")["likelySubtags"],
        "timeData": {
            key: [value["_preferred"], value["_allowed"].split()]
            for key, value in read("timeData")["timeData"].items()
        },
        "calendars": read("calendarPreferenceData")["calendarPreferenceData"],
        "dayPeriodRules": read("dayPeriods")["dayPeriodRuleSet"],
        "digits": {
            key: value["_digits"]
            for key, value in read("numberingSystems")["numberingSystems"].items()
            if value["_type"] == "numeric"
        },
        "languageAliases": {
            key: value["_replacement"]
            for key, value in aliases["languageAlias"].items()
            if "-" not in key and " " not in value["_replacement"]
        },
        "territoryAliases": {
            key: value["_replacement"]
            for key, value in aliases["territoryAlias"].items()
            if " " not in value["_replacement"]
        },
    }


def _generator_calendars(locales: _Tree, available: dict[str, str]) -> dict[str, str]:
    """The calendar ICU's pattern generator reads for each tag, where it is not
    Gregorian. ICU takes it from the first ``calendar/default`` up the locale's
    chain (not from the region, as Intl's own calendar), and starts that chain
    at an alias's own name: ``uz-AF`` (an alias of ``uz-Arab-AF``) climbs
    ``uz``, not ``uz-Arab`` (Persian), so it formats Persian dates with
    Gregorian patterns."""
    aliases = {target: name for name in locales.names() if (target := locales.alias_of(name))}
    found: dict[str, str] = {}
    for tag, name in available.items():
        start = aliases.get(name, name)
        current: str | None = start
        while current is not None:
            default = (
                locales.own(current, ["calendar", "default"]) if locales.has(current) else None
            )
            if isinstance(default, str):
                if default != "gregorian":
                    found[tag] = default
                break
            current = (
                locales.parent(current)
                if locales.has(current)
                else (current.rsplit("_", 1)[0] if "_" in current else "root")
            )
    return found


def _node(tags: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["node", "-e", _NODE], input=json.dumps(tags), capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def _write(archive: zipfile.ZipFile, name: str, text: str) -> None:
    # A fixed date, so the same data gives the same bytes.
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, text, compresslevel=9)


def _bcp47(icu_name: str) -> str:
    return "und" if icu_name == "root" else icu_name.replace("_", "-")


def generate(folder: Path) -> None:
    versions = _node([])
    data = _icu_data(folder, versions["icu"])
    locales, zones = _Tree(data, "locales"), _Tree(data, "zone")
    names = [name for name in data.namelist() if name.startswith("data/locales/")]
    tags = sorted({_bcp47(Path(name).stem) for name in names if name.endswith(".txt")} - {"und"})
    node = _node(tags)
    available: dict[str, str] = {}
    for tag in node["available"]:
        icu_name = tag.replace("-", "_")
        icu_name = locales.alias_of(icu_name) or icu_name
        while not locales.has(icu_name) and "_" in icu_name:
            icu_name = icu_name.rsplit("_", 1)[0]
        available[tag] = icu_name
    needed: set[str] = set()
    for icu_name in available.values():
        needed.update(locales.chain(icu_name))
    supplemental = _supplemental(_cldr_core(folder, node["cldr"]))
    systems = sorted(supplemental["digits"])
    resolved = {name: _locale(locales, zones, name, systems) for name in sorted(needed)}
    parents = {
        _bcp47(name): _bcp47(up)
        for name in needed
        if (up := locales.parent(name)) is not None and up != name.rsplit("_", 1)[0]
    }
    meta = {
        "node": node["node"],
        "icu": node["icu"],
        "cldr": node["cldr"],
        "tz": node["tz"],
        "available": {tag: _bcp47(name) for tag, name in available.items()},
        "parents": parents,
        "generatorCalendars": _generator_calendars(locales, available),
        "metazones": _icu_metazones(folder, node["tz"]),
        **supplemental,
    }
    _TARGET.parent.mkdir(parents=True, exist_ok=True)
    license_url = f"https://raw.githubusercontent.com/unicode-org/icu/release-{node['icu']}/LICENSE"
    _LICENSE.write_bytes(_fetch(license_url, folder / f"LICENSE-icu-{node['icu']}").read_bytes())
    with zipfile.ZipFile(_TARGET, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        _write(archive, "meta.json", json.dumps(meta, ensure_ascii=False, sort_keys=True))
        for name, found in resolved.items():
            up = locales.parent(name)
            diff = found if up is None else _diff(found, resolved[up])
            text = json.dumps(diff, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            _write(archive, f"locales/{_bcp47(name)}.json", text)


def main() -> None:
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
        folder.mkdir(parents=True, exist_ok=True)
        generate(folder)
        return
    with tempfile.TemporaryDirectory() as folder:
        generate(Path(folder))


if __name__ == "__main__":
    main()
