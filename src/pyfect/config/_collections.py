"""``list_of`` and ``dict_of`` (Effect's ``Config.Array`` and ``Config.Record``):
a container read from structural provider input or from one separated
string (``"a,b"``, ``"k=v,k2=v2"``).

Each is a first-match choice between the two readings. When neither
applies, the issues of both are reported, and the config is absent unless
the node held something either reading could use.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.cause import Cause, Fail
from pyfect.config._config import Config, Resolution, require_config
from pyfect.config._error import ConfigError
from pyfect.config._leaf import EXPECTED_STRING, at, composite, expected, load
from pyfect.config_provider import Array, ConfigProvider, Node, Path, Record, Value, make
from pyfect.effect import fail, fail_cause, succeed
from pyfect.result import Err, Ok, Result
from pyfect.schema import SchemaError
from pyfect.schema.issue import Issue

type Decoded[A] = Result[A, Issue]
"""A reading's value, or the issue that rules it out."""

type Reading[A] = Callable[[ConfigProvider, Path, Node | None], Effect[Decoded[A], ConfigError]]


def list_of[A](
    element: Config[A], name: str | None = None, *, separator: str = ","
) -> Config[list[A]]:
    """A list whose items are read with ``element``: from a separated
    string (``"1,2"``; ``""`` is empty), else from an array node
    (``PORTS_0``, ``PORTS_1`` in ``from_env``)."""
    require_config(element, "element")

    def from_string(provider: ConfigProvider, path: Path, node: Node | None) -> Effect[Any, Any]:
        text = None if node is None else node.value
        if text is None:
            return succeed(Err(at(path, EXPECTED_STRING)))
        pieces = _split(text, separator) if text else []
        return _read_pieces(element, [((*path, i), piece) for i, piece in enumerate(pieces)])

    def from_array(provider: ConfigProvider, path: Path, node: Node | None) -> Effect[Any, Any]:
        if not isinstance(node, Array):
            return succeed(Err(at(path, expected("array"))))
        children = _load_children(provider, [(*path, i) for i in range(node.length)])
        return children.flat_map(lambda items: _read_children(element, provider, items))

    def has_input(node: Node | None) -> bool:
        return isinstance(node, Array) or (node is not None and node.value is not None)

    return _container(name, (from_string, from_array), has_input, _as_list)


def dict_of[A](
    value: Config[A],
    name: str | None = None,
    *,
    separator: str = ",",
    key_value_separator: str = "=",
) -> Config[dict[str, A]]:
    """A dict whose values are read with ``value``: from a record node
    (its keys that hold something), else from a separated string (``"a=1,b=2"``; a pair with
    no separator, an empty key or an empty value is skipped)."""
    require_config(value, "value")

    def from_record(provider: ConfigProvider, path: Path, node: Node | None) -> Effect[Any, Any]:
        if not isinstance(node, Record):
            return succeed(Err(at(path, expected("object"))))
        children = _load_children(provider, [(*path, k) for k in sorted(node.keys)])
        return children.flat_map(lambda items: _read_present(value, provider, items))

    def from_string(provider: ConfigProvider, path: Path, node: Node | None) -> Effect[Any, Any]:
        text = None if node is None else node.value
        if text is None:
            return succeed(Err(at(path, EXPECTED_STRING)))
        pairs = _split_key_value(text, separator, key_value_separator)
        keys = list(pairs)
        return _read_pieces(value, [((*path, k), pairs[k]) for k in keys]).map(_keyed(keys))

    def has_input(node: Node | None) -> bool:
        return isinstance(node, Record) or (node is not None and node.value is not None)

    return _container(name, (from_record, from_string), has_input, _as_dict)


def _keyed[A](keys: list[str]) -> Callable[[Decoded[list[A]]], Decoded[dict[str, A]]]:
    def to_dict(decoded: Decoded[list[A]]) -> Decoded[dict[str, A]]:
        match decoded:
            case Ok(values):
                return Ok(dict(zip(keys, values, strict=True)))
            case Err():
                return decoded

    return to_dict


def _as_list(values: Any) -> list[Any]:
    return list(values)


def _as_dict(values: Any) -> dict[str, Any]:
    return dict(values)


def _container[A](
    name: str | None,
    readings: tuple[Reading[Any], Reading[Any]],
    has_input: Callable[[Node | None], bool],
    build: Callable[[Any], A],
) -> Config[A]:
    local: Path = () if name is None else (name,)
    first, second = readings

    def run(provider: ConfigProvider, prefix: Path) -> Effect[Resolution[A], ConfigError]:
        path = (*prefix, *local)

        def choose(node: Node | None) -> Effect[Resolution[A], ConfigError]:
            def try_second(issue: Issue) -> Effect[Resolution[A], ConfigError]:
                def settle(decoded: Decoded[Any]) -> Effect[Resolution[A], ConfigError]:
                    match decoded:
                        case Ok(values):
                            return succeed(Ok(build(values)))
                        case Err(second_issue):
                            error = ConfigError(SchemaError(composite(issue, second_issue)))
                            return succeed(Err(error)) if not has_input(node) else fail(error)

                return second(provider, path, node).flat_map(settle)

            def after_first(decoded: Decoded[Any]) -> Effect[Resolution[A], ConfigError]:
                match decoded:
                    case Ok(values):
                        return succeed(Ok(build(values)))
                    case Err(issue):
                        return try_second(issue)

            return first(provider, path, node).flat_map(after_first)

        return load(provider, path).flat_map(choose)

    return Config(run)


type Child = tuple[Path, Node | None]
"""A container item's path and the node loaded there."""


def _load_children(
    provider: ConfigProvider, paths: Sequence[Path]
) -> Effect[list[Child], ConfigError]:
    """Every item's node, loaded before any item is decoded, as Effect
    materializes a container: a later item's source error wins over an
    earlier item's invalid value."""
    return for_each(paths, lambda path: load(provider, path).map(lambda node: (path, node)))


def _read_children[A](
    element: Config[A], provider: ConfigProvider, children: Sequence[Child]
) -> Effect[Decoded[list[A]], ConfigError]:
    """Each item read with ``element`` through a provider that already holds
    its node; the first issue rules the reading out."""
    return _first_issue(
        [_read_item(element, _holding(provider, path, node), path) for path, node in children]
    )


def _read_present[A](
    element: Config[A], provider: ConfigProvider, children: Sequence[Child]
) -> Effect[Decoded[dict[str, A]], ConfigError]:
    """A record's entries: keys with no node are left out, as in Effect."""
    present = [(path, node) for path, node in children if node is not None]
    keys = [str(path[-1]) for path, _ in present]
    return _read_children(element, provider, present).map(_keyed(keys))


def _read_pieces[A](
    element: Config[A], pieces: Sequence[tuple[Path, str]]
) -> Effect[Decoded[list[A]], ConfigError]:
    """Each piece of a split string read with ``element``, as if the
    provider held the piece at its item path."""
    return _read_children(element, _NOTHING, [(path, Value(piece)) for path, piece in pieces])


def _holding(provider: ConfigProvider, path: Path, node: Node | None) -> ConfigProvider:
    return make(lambda p: succeed(node) if p == path else provider.load(p))


_NOTHING = make(lambda _path: succeed(None))


def _split(text: str, separator: str) -> list[str]:
    """JavaScript's ``split``: an empty separator splits into characters."""
    return text.split(separator) if separator else list(text)


def _first_issue[A](
    reads: list[Effect[Decoded[A], ConfigError]],
) -> Effect[Decoded[list[A]], ConfigError]:
    def collect(decoded: list[Decoded[A]]) -> Decoded[list[A]]:
        values: list[A] = []
        for item in decoded:
            match item:
                case Ok(v):
                    values.append(v)
                case Err():
                    return item
        return Ok(values)

    return _sequence_until_issue(reads).map(collect) if reads else succeed(Ok([]))


def _sequence_until_issue[A](
    reads: list[Effect[Decoded[A], ConfigError]],
) -> Effect[list[Decoded[A]], ConfigError]:
    """Run the reads in order, stopping after the first issue (later items
    are not decoded, as a schema stops at its first error)."""

    def step(i: int, done: list[Decoded[A]]) -> Effect[list[Decoded[A]], ConfigError]:
        if i == len(reads):
            return succeed(done)

        def next_read(item: Decoded[A]) -> Effect[list[Decoded[A]], ConfigError]:
            done.append(item)
            return succeed(done) if isinstance(item, Err) else step(i + 1, done)

        return reads[i].flat_map(next_read)

    return step(0, [])


def _read_item[A](
    element: Config[A], provider: ConfigProvider, path: Path
) -> Effect[Decoded[A], ConfigError]:
    """One item: its value, or the issue that it is absent or invalid.
    Source errors, defects and interruptions propagate."""

    def on_failure(cause: Cause[ConfigError]) -> Effect[Decoded[A], ConfigError]:
        match cause.reasons:
            case (Fail(ConfigError(SchemaError(issue))),):
                return succeed(Err(issue))
            case _:
                return fail_cause(cause)

    def on_success(resolution: Resolution[A]) -> Effect[Decoded[A], ConfigError]:
        match resolution:
            case Ok():
                return succeed(resolution)
            case Err(ConfigError(SchemaError(issue))):
                return succeed(Err(issue))
            case Err(error):
                return fail(error)

    return element._evaluate(provider, path).match_cause_effect(
        on_failure=on_failure, on_success=on_success
    )


def _split_key_value(text: str, separator: str, key_value_separator: str) -> dict[str, str]:
    """Effect's ``splitKeyValue``: a pair splits at its first separator."""
    pairs: dict[str, str] = {}
    for pair in _split(text, separator):
        if key_value_separator == "":
            key, value = pair[:1], pair[1:2]
        else:
            index = pair.find(key_value_separator)
            if index <= 0:
                continue
            key, value = pair[:index], pair[index + len(key_value_separator) :]
        if key and value:
            pairs[key] = value
    return pairs
