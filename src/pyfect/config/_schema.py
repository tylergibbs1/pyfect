"""``config.schema``: a config decoded with a schema (Effect's ``Config.schema``).

The schema is first turned into its canonical string-tree codec
(``S.to_codec_string_tree``); the encoded shape of that codec says what to
load. Each node of the encoded shape gets one more link, from a *cursor*
(a provider, a path and the node found there): an object loads its declared
keys and the record keys an index signature accepts, an array loads its
items, a scalar reads the string at its own path. The schema's own parser
then drives the loading, so unions, checks and errors work as they do for
any input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Never, cast, final

from pyfect._core import Effect
from pyfect.cause import Cause, Die, Fail, Interrupt, Reason
from pyfect.config._config import Config, Resolution
from pyfect.config._error import ConfigError
from pyfect.config_provider import Array, ConfigProvider, Node, Path, Record, SourceError
from pyfect.effect import fail, fail_cause, succeed
from pyfect.result import Err, Ok
from pyfect.schema import Codec, SchemaError, ast
from pyfect.schema import transformation as T
from pyfect.schema._to_codec_string_tree import to_codec_string_tree_ast
from pyfect.schema.ast._result import NotAnObject
from pyfect.schema.issue import Issue, Pointer

_OPAQUE = "Config.schema does not support opaque StringTree encodings"


@final
class _Undefined(NotAnObject):
    """What a cursor reads where the provider has nothing usable: Effect's
    ``undefined``, which no schema a config can use accepts."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "undefined"


_UNDEFINED = _Undefined()


@dataclass(frozen=True, slots=True)
class _Cursor:
    provider: ConfigProvider
    path: Path
    node: Node | None

    def __str__(self) -> str:
        return "<configuration>"


def schema[A](codec: Codec[A, object, Never, object], path: str | Path | None = None) -> Config[A]:
    """A config decoded by ``codec`` from what the provider holds at
    ``path`` (one key, or a path of keys and indexes; ``None``: the
    config's own path).

    The codec's string-tree form says what to load: a struct or record
    reads an object, a tuple or array reads indexed items (``A_0``,
    ``A_1`` in ``from_env``), anything else one string; a union loads each
    member by its own shape. Missing input that the codec rejects is
    absent (``with_default`` applies); invalid input fails. A codec with
    an opaque encoding (``S.Unknown``, ``S.Any``, ``S.Json``, anywhere in
    it) raises ``ValueError`` here."""
    root = to_codec_string_tree_ast(codec.__codec__().ast)
    encoded = ast.to_encoded(root)
    decoder = _CursorWalk().recur(root)
    local: Path = () if path is None else (path,) if isinstance(path, str) else path

    def run(provider: ConfigProvider, prefix: Path) -> Effect[Resolution[A], ConfigError]:
        full = (*prefix, *local)

        def decode(cursor: _Cursor) -> Effect[Resolution[A], Any]:
            def failed(issue: Issue) -> Effect[Resolution[A], ConfigError]:
                error = ConfigError(SchemaError(Pointer(full, issue) if full else issue))
                if _has_input(encoded, cursor.node):
                    return fail(error)
                return succeed(Err(error))

            return cast("Effect[A, Issue]", ast.to_effect(decoder.parse(cursor, {}))).match_effect(
                on_failure=failed, on_success=lambda value: succeed(Ok(value))
            )

        return _load(provider, full).flat_map(decode).catch_cause(_source_errors)

    return Config(run)


def _load(provider: ConfigProvider, path: Path) -> Effect[_Cursor]:
    """The cursor at ``path``. A source error travels as a defect, so no
    schema recovers from it; ``schema`` turns it back into a failure."""

    def to_defect(cause: Cause[SourceError]) -> Effect[Never]:
        return fail_cause(Cause(tuple(map(_as_defect, cause.reasons))))

    return (
        provider.load(path).catch_cause(to_defect).map(lambda node: _Cursor(provider, path, node))
    )


def _as_defect(reason: Reason[SourceError]) -> Reason[Never]:
    match reason:
        case Fail(error):
            return Die(error, annotations=reason.annotations)
        case Die() | Interrupt():
            return reason


def _source_errors(cause: Cause[Any]) -> Effect[Never, ConfigError]:
    return fail_cause(Cause(tuple(map(_as_failure, cause.reasons))))


def _as_failure(reason: Reason[Any]) -> Reason[Any]:
    match reason:
        case Die(SourceError() as error):
            return Fail(ConfigError(error), annotations=reason.annotations)
        case _:
            return reason


def _has_input(node: ast.AST, found: Node | None) -> bool:
    """``found`` holds something the encoded shape ``node`` could read."""
    match node:
        case ast.Objects():
            return isinstance(found, Record)
        case ast.Arrays():
            return isinstance(found, Array)
        case ast.Union():
            return any(_has_input(member, found) for member in node.types)
        case ast.Suspend():
            return _has_input(node.target, found)
        case ast.Class():
            return isinstance(found, Record)
        case _:
            return found is not None and found.value is not None


def _is_scalar(node: ast.AST) -> bool:
    match node:
        case ast.Union():
            return all(map(_is_scalar, node.types))
        case ast.Objects() | ast.Arrays() | ast.Suspend() | ast.Class():
            return False
        case _:
            return True


type _Materialize = Callable[[_Cursor], Effect[object]]


def _from_cursor(node: ast.AST, materialize: _Materialize) -> ast.AST:
    """``node`` decoding from a cursor: ``materialize`` loads what it reads."""

    def decode(cursor: object, _options: object) -> Effect[object]:
        return materialize(cast("_Cursor", cursor))

    def encode(value: object, _options: object) -> Effect[object]:
        return succeed(value)

    return ast.decode_to(ast.unknown, node, T.transform_effect(decode=decode, encode=encode))


def _scalar(cursor: _Cursor) -> Effect[object]:
    value = None if cursor.node is None else cursor.node.value
    return succeed(_UNDEFINED if value is None else value)


def _child(cursor: _Cursor, segment: str | int) -> Effect[_Cursor]:
    return _load(cursor.provider, (*cursor.path, segment))


class _CursorWalk:
    """Effect's ``toConfigCursorAST``: each node of the encoded shape (the
    node, or the last node of its encoding chain) decodes from a cursor."""

    def __init__(self) -> None:
        self._done: dict[int, tuple[ast.AST, ast.AST]] = {}
        self._seen: set[int] = set()

    def recur(self, node: ast.AST) -> ast.AST:
        hit = self._done.get(id(node))
        if hit is not None:
            return hit[1]
        self._seen.add(id(node))
        if node.encoding is None:
            out = self._step(node)
        else:
            *init, last = node.encoding
            out = replace(
                node, encoding=(*init, ast.Link(self.recur(last.to), last.transformation))
            )
        self._done[id(node)] = (node, out)
        if isinstance(out, ast.Class) and isinstance(out.shape, _CursorShape):
            # Walk the fields now, with the class memoized, so an opaque
            # encoding raises when the config is made.
            out.shape.start()
        return out

    def _step(self, node: ast.AST) -> ast.AST:
        match node:
            case ast.Objects():
                properties = tuple(replace(p, type=self.recur(p.type)) for p in node.properties)
                indexes = tuple(
                    ast.IndexSignature(i.parameter, self.recur(i.type))
                    for i in node.index_signatures
                )
                rebuilt = replace(node, properties=properties, index_signatures=indexes)
                return _from_cursor(rebuilt, _objects(node))
            case ast.Arrays():
                elements = tuple(ast.Element(self.recur(e.type), e.optional) for e in node.elements)
                rest = tuple(map(self.recur, node.rest))
                return _from_cursor(replace(node, elements=elements, rest=rest), _arrays)
            case ast.Union():
                types = tuple(map(self.recur, node.types))
                if not _is_scalar(node):
                    return replace(node, types=types)
            case ast.Suspend():
                target = node.target
                # Walk new targets now, so an opaque encoding raises when
                # the config is made.
                if id(target) not in self._seen:
                    self.recur(target)
                return replace(node, thunk=lambda: self.recur(target))
            case ast.Declaration() | ast.Any():
                raise ValueError(_OPAQUE)
            case ast.Class():
                return self._class(node)
            case _:
                pass
        return _from_cursor(node, _scalar)

    def _class(self, node: ast.Class) -> ast.AST:
        # A class reads its fields' struct, as Effect's class declaration
        # links it.
        match node.side:
            case "decode":
                return replace(node, shape=_CursorShape(node.shape, self))
            case "encoded":
                return self.recur(node.shape.encoded)
            case "type" | "encode":
                raise ValueError(_OPAQUE)


def _objects(node: ast.Objects) -> _Materialize:
    names = [p.name for p in node.properties if isinstance(p.name, str)]

    def materialize(cursor: _Cursor) -> Effect[object]:
        found = cursor.node
        if not isinstance(found, Record):
            return succeed(_UNDEFINED)
        keys = list(dict.fromkeys(names))
        if node.index_signatures:
            for key in found.keys:
                if key not in keys and any(i.selects(key) for i in node.index_signatures):
                    keys.append(key)
        out: dict[str, _Cursor] = {}

        def load(i: int) -> Effect[object]:
            if i == len(keys):
                return succeed(out)

            def keep(child: _Cursor) -> Effect[object]:
                if child.node is not None:
                    out[keys[i]] = child
                return load(i + 1)

            return _child(cursor, keys[i]).flat_map(keep)

        return load(0)

    return materialize


def _arrays(cursor: _Cursor) -> Effect[object]:
    found = cursor.node
    if not isinstance(found, Array):
        return succeed(_UNDEFINED)
    out: list[_Cursor] = []

    def load(i: int) -> Effect[object]:
        if i == found.length:
            return succeed(out)

        def keep(child: _Cursor) -> Effect[object]:
            out.append(child)
            return load(i + 1)

        return _child(cursor, i).flat_map(keep)

    return load(0)


class _CursorShape:
    """A schema class decoding its fields from a cursor. The fields are
    walked on first use, after the class node is memoized, so a field that
    refers back to the class meets its walked node."""

    __slots__ = ("_fields", "_started", "base", "walk")

    def __init__(self, base: ast.ClassShape, walk: _CursorWalk) -> None:
        self.base = base
        self.walk = walk
        self._fields: ast.Objects | None = None
        self._started = False

    @property
    def fields(self) -> ast.Objects:
        if self._fields is None:
            self._started = True
            self._fields = cast("ast.Objects", self.walk.recur(self.base.fields))
        return self._fields

    def start(self) -> None:
        """Walk the fields unless that already began."""
        if not self._started:
            self.fields  # noqa: B018

    @property
    def cls(self) -> type:
        return self.base.cls

    @property
    def encoded(self) -> ast.AST:
        return self.base.encoded

    @property
    def checks(self) -> ast.Checks | None:
        return self.base.checks

    def construct(self, values: dict[object, object]) -> object:
        return self.base.construct(values)

    def values_of(self, instance: object) -> dict[object, object]:
        return self.base.values_of(instance)
