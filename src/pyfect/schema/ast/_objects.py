"""``Objects``: a mapping with declared keys (a struct) and key patterns (a
record), Effect's ``Objects``.

A ``PropertySignature`` is one declared key: required, optional (absent
from the output when absent from the input) or defaulted (a missing key
takes ``default()``, on the decoding side only). A missing key whose node
has an encoding is given to it as ``MISSING``: a getter may supply a value
(Effect's ``withDefault``). An ``IndexSignature`` takes every other key its
``parameter`` node accepts, with values of its ``type``. A key no signature
takes is excess: dropped, or an ``UnexpectedKey`` under
``on_excess_property="error"``.

The input is any ``Mapping`` or object: as in JavaScript, an instance's attributes are its
keys, its own ones when enumerating (``_ObjectKeys``). The output is a new ``dict``. An empty
struct is the type ``{}``: any value but ``None``, as it came.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, cast, final

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import (
    AST,
    at_key,
    construct_missing,
    dispatching,
    encoded_optional,
    invalid_type,
    issue_of,
    map_or_same,
)
from pyfect.schema.ast._encoding import to_encoded
from pyfect.schema.ast._result import MISSING, NotAnObject, ParseResult, call
from pyfect.schema.ast._steps import Abort, Pending, Steps, Stop, Suspended, run_steps
from pyfect.schema.ast._suspend import Suspend
from pyfect.schema.issue import Composite, Issue, MissingKey, Pointer, UnexpectedKey, reported

_NOT_OBJECTS = (type(None), bool, int, float, complex, str, bytes, list, tuple, NotAnObject)
"""What JavaScript's ``typeof input === "object"`` and ``!Array.isArray`` turn away."""


class ObjectKeys(Mapping[object, object]):
    """An instance read as keys: any attribute, and its own ones when enumerating."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __getitem__(self, key: object) -> object:
        if isinstance(key, str):
            try:
                return getattr(self.value, key)
            except AttributeError:
                pass
        raise KeyError(key)  # pragma: no mutate, never shown

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and hasattr(self.value, key)

    def __iter__(self) -> Iterator[object]:
        return iter(_own_attributes(self.value))

    def __len__(self) -> int:
        return len(_own_attributes(self.value))

    def __repr__(self) -> str:
        return repr(self.value)  # pragma: no mutate, debug only


def reads_properties(value: object) -> bool:
    return not isinstance(value, _NOT_OBJECTS) and not callable(value)


def _own_attributes(value: object) -> list[str]:
    names: list[str] = list(getattr(value, "__dict__", ()))
    for cls in type(value).__mro__:
        slots: object = cls.__dict__.get("__slots__", ())
        for name in (slots,) if isinstance(slots, str) else cast("tuple[str, ...]", slots):
            if name not in names and name != "__weakref__" and hasattr(value, name):
                names.append(name)
    return names


@dataclass(frozen=True, slots=True)
class PropertySignature:
    """A declared key ``name`` with values of ``type``."""

    name: Hashable
    type: AST
    optional: bool = False
    default: Callable[[], object] | None = None
    """Makes the decoded value of a missing key (a class field's default)."""
    encoded_optional: bool | None = None
    """Whether the key may be missing on the other side; ``None`` works it
    out when flipping (optional or defaulted here, or an optional source of
    the node's transformation)."""

    def flips_to_itself(self) -> bool:
        """Its flip would declare the same key the same way."""
        return (
            self.default is None
            and self.type.flip() is self.type
            and self.optional_when_encoded() == self.optional
        )

    def optional_when_encoded(self) -> bool:
        """Whether the key may be missing from the encoded input."""
        if self.encoded_optional is not None:
            return self.encoded_optional
        return self.default is not None or encoded_optional(self.type, optional=self.optional)

    def flipped(self) -> PropertySignature:
        type = self.type.flip()
        return PropertySignature(self.name, type, self.optional_when_encoded(), None, self.optional)


_KEY_KINDS = frozenset({"String", "Number", "TemplateLiteral", "Enum", "Suspend"})
"""The nodes of keys. ``Enum`` and ``Suspend`` are Python's: an enum's keys
decode to members (Effect's ``record`` makes its values required keys), and a
suspended key (a reference in a representation) is not made to be checked."""


def _is_key_node(ast: AST) -> bool:
    if ast.tag == "Union":
        return all(_is_key_node(member) for member in ast.children())
    return ast.tag in _KEY_KINDS


def _is_key_encoding(ast: AST) -> bool:
    while ast.encoding is not None:
        ast = ast.encoding[-1].to
    if ast.tag == "Union":
        return all(_is_key_encoding(member) for member in ast.children())
    return ast.tag in _KEY_KINDS


@dataclass(frozen=True, slots=True)
class IndexSignature:
    """Every key ``parameter`` accepts, with values of ``type``. The
    parameter is a ``String``, ``Number``, ``TemplateLiteral``, ``Enum``,
    ``Suspend`` or a union of them, on both its sides; another raises
    ``ValueError``."""

    parameter: AST
    type: AST

    def __post_init__(self) -> None:
        parameter = self.parameter
        if not (_is_key_node(parameter) and _is_key_encoding(parameter)):
            raise ValueError(f"Invalid index signature parameter {parameter.tag}")

    def selects(self, key: object, options: ParseOptions | None = None) -> bool:
        """``key`` is a value of the parameter's encoded side."""
        return type(self.parameter.flip().to_type().parse(key, options or {})) is Success


def get_index_signature_keys(
    input: Mapping[Any, object], parameter: AST, options: ParseOptions | None = None
) -> list[Any]:
    """The keys of ``input`` that an index signature with ``parameter``
    takes (Effect's ``getIndexSignatureKeys``): those its encoded side
    accepts. A union's are its members' in member order, each key once."""
    return _index_signature_keys(input, to_encoded(parameter), options or {})


def _index_signature_keys(
    input: Mapping[Any, object], node: AST, options: ParseOptions
) -> list[object]:
    if node.tag == "Union" and node.checks is None and node.encoding is None:
        return list(
            dict.fromkeys(
                key
                for member in node.children()
                for key in _index_signature_keys(input, member, options)
            )
        )
    return [key for key in input if type(node.parse(key, options)) is Success]


@dataclass(frozen=True, slots=True, eq=False)
class Objects(AST):
    """A mapping with ``properties`` and ``index_signatures``."""

    properties: tuple[PropertySignature, ...] = ()
    index_signatures: tuple[IndexSignature, ...] = ()
    tag = "Objects"

    def get_expected(self) -> str:
        return "object" if self.properties or self.index_signatures else "object | array"

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        if not self.properties and not self.index_signatures:
            refused = input is None or isinstance(input, NotAnObject)
            return invalid_type(self, input, options) if refused else Success(input)
        keys: Mapping[object, object]
        if isinstance(input, Mapping):
            keys = cast("Mapping[object, object]", input)
        elif reads_properties(input):
            keys = ObjectKeys(input)
        else:
            return invalid_type(self, input, options)
        return call(_parse_keys, self, cast("object", input), keys, options)

    def _flip(self) -> Objects:
        # Checks describe the decoded side: flipped, they check the input
        # (Effect swaps ``checks`` and ``encodingChecks``). As in Effect, a
        # struct whose parts all flip to themselves is its own flip.
        properties = tuple(p if p.flips_to_itself() else p.flipped() for p in self.properties)
        indexes = tuple(
            i
            if i.parameter.flip() is i.parameter and i.type.flip() is i.type
            else IndexSignature(i.parameter.flip(), i.type.flip())
            for i in self.index_signatures
        )
        if (
            self.checks is None
            and self.encoding_checks is None
            and all(a is b for a, b in zip(properties, self.properties, strict=True))
            and all(a is b for a, b in zip(indexes, self.index_signatures, strict=True))
        ):
            return self
        return replace(
            self,
            properties=properties,
            index_signatures=indexes,
            checks=self.encoding_checks,
            encoding_checks=self.checks,
        )

    def _to_type(self) -> Objects:
        def typed_property(p: PropertySignature) -> PropertySignature:
            type = p.type.to_type()
            return p if type is p.type else replace(p, type=type)

        def typed_index(i: IndexSignature) -> IndexSignature:
            parameter, type = i.parameter.to_type(), i.type.to_type()
            if parameter is i.parameter and type is i.type:
                return i
            return IndexSignature(parameter, type)

        properties = map_or_same(self.properties, typed_property)
        indexes = map_or_same(self.index_signatures, typed_index)
        if properties is self.properties and indexes is self.index_signatures:
            return self
        return replace(self, properties=properties, index_signatures=indexes)

    def children(self) -> Iterator[AST]:
        for p in self.properties:
            yield p.type
        for i in self.index_signatures:
            yield i.parameter
            yield i.type

    def _keeps_structural_checks(self) -> bool:
        return True


_SKIPPED = object()
"""A child's value that failed under ``errors="all"``."""


_NO_KEYS: frozenset[Hashable] = frozenset()
_NO_ENTRIES: tuple[tuple[IndexSignature, object], ...] = ()


def _parse_keys(
    ast: Objects, input: object, keys: Mapping[object, object], options: ParseOptions
) -> ParseResult:
    return run_steps(_Run(ast, input, keys, options), options.get("concurrency"))


@final
class _Run(Steps["_Run"]):
    """One parse of a mapping: the output so far and the issues found.
    Steps: the excess-key check, then each property, then each key an
    index signature selects."""

    __slots__ = ("ast", "declared", "entries", "input", "issues", "keys", "options", "out")

    def __init__(
        self,
        ast: Objects,
        input: object,
        keys: Mapping[object, object],
        options: ParseOptions,
    ) -> None:
        self.ast = ast
        self.input = input
        self.keys = keys
        self.options = options
        self.out: dict[object, object] = {}
        self.issues: list[Issue] = []
        self.entries: tuple[tuple[IndexSignature, object], ...] | None = _NO_ENTRIES
        if ast.index_signatures:
            self.declared: frozenset[Hashable] = frozenset(p.name for p in ast.properties)
            # Listed on first use: strict parsing's excess check lists the keys
            # before reading any property; otherwise after them, as in Effect.
            self.entries = None
        else:
            self.declared = _NO_KEYS

    def _listed(self) -> tuple[tuple[IndexSignature, object], ...]:
        """The keys each index signature takes, listed on first use."""
        entries = self.entries
        if entries is None:
            options = self.options
            entries = self.entries = tuple(
                (i, key)
                for i in self.ast.index_signatures
                for key in get_index_signature_keys(self.keys, i.parameter, options)
            )
        return entries

    def copy(self) -> _Run:
        other = _Run.__new__(_Run)
        other.ast, other.input, other.keys = self.ast, self.input, self.keys
        other.options = self.options
        other.entries, other.declared = self.entries, self.declared
        other.out = dict(self.out)
        other.issues = list(self.issues)
        return other

    def size(self) -> int:
        return 1 + len(self.ast.properties) + len(self._listed())  # pragma: no mutate, idle worker

    def finish(self) -> Exit[object, Issue]:
        if self.issues:
            issues = self.issues
            return fail_exit(
                Composite(self.ast, (issues[0], *issues[1:]), reported(self.input, self.options))
            )
        return Success(self.out)

    def run_from(self, start: int) -> Suspended[_Run] | None:
        """Steps: ``0`` checks excess keys, ``1 + i`` parses property
        ``i``, then one per entry an index signature selects."""
        if start == 0:
            self._excess()
            start = 1
        properties = self.ast.properties
        input, options, out = self.keys, self.options, self.out
        for i in range(start - 1, len(properties)):
            prop = properties[i]
            name = prop.name
            if name in input:
                result = prop.type.parse(input[name], options)
                if type(result) is Success and result.value is not MISSING:
                    out[name] = result.value
                    continue
            else:
                result = self._missing(prop)
                if result is None:
                    continue
            if isinstance(result, (Success, Failure)):
                self._set_property(prop, result)
            else:
                return i + 1, Pending(result, _Run.property_of(prop))
        first_entry = len(properties) + 1
        entries = self._listed()
        for i in range(max(start, first_entry) - first_entry, len(entries)):
            pending = self._entry(*entries[i])
            if pending is not None:
                return first_entry + i, pending
        return None

    @staticmethod
    def property_of(prop: PropertySignature) -> Callable[[_Run, Exit[object, Issue]], None]:
        return lambda run, exit: run._set_property(prop, exit)

    def _excess(self) -> None:
        if self.options.get("on_excess_property") != "error":
            return
        ast = self.ast
        declared = {p.name for p in ast.properties}
        selected = {key for _, key in self._listed()}
        for key, value in self.keys.items():
            if key not in declared and key not in selected:
                self._report(key, UnexpectedKey(ast, reported(value, self.options)))

    def _report(self, key: object, issue: Issue) -> None:
        self.issues.append(Pointer((cast("Hashable", key),), issue))  # pragma: no mutate, a cast
        if self.options.get("errors") != "all":
            raise Stop

    def _value(self, key: object, exit: Exit[object, Issue]) -> object:
        """The parsed value, or ``_SKIPPED`` once its issue is reported."""
        if type(exit) is Success:
            return exit.value
        failure = cast("Failure[Issue]", exit)
        issue = issue_of(failure)
        if issue is None:
            raise Abort(at_key(self.ast, cast("Hashable", key), failure, self.input, self.options))
        self._report(key, issue)
        return _SKIPPED

    def _missing(self, prop: PropertySignature) -> ParseResult | None:
        """The parse of a missing key, or ``None`` once it is settled."""
        constructed = construct_missing(prop.type, self.options)
        if constructed is not None:
            return constructed
        if prop.default is not None:
            self.out[prop.name] = prop.default()
            return None
        if prop.type.encoding is not None or isinstance(prop.type, Suspend) or dispatching():
            return prop.type.parse(MISSING, self.options)
        if not prop.optional:
            self._report(prop.name, MissingKey(prop.type.key_annotations))
        return None

    def _set_property(self, prop: PropertySignature, exit: Exit[object, Issue]) -> None:
        value = self._value(prop.name, exit)
        if value is MISSING:
            if not prop.optional:
                self._report(prop.name, MissingKey(prop.type.key_annotations))
        elif value is not _SKIPPED:
            self.out[prop.name] = value

    def _entry(self, index: IndexSignature, key: object) -> Pending[_Run] | None:
        result = index.parameter.parse(key, self.options)
        if isinstance(result, (Success, Failure)):
            return self._entry_value(index, key, result)
        return Pending(result, lambda run, exit: run._entry_value(index, key, exit))

    def _entry_value(
        self, index: IndexSignature, key: object, key_exit: Exit[object, Issue]
    ) -> Pending[_Run] | None:
        out_key = self._value(key, key_exit)
        result = index.type.parse(self.keys[key], self.options)
        if isinstance(result, (Success, Failure)):
            self._set_entry(key, out_key, result)
            return None
        return Pending(result, lambda run, exit: run._set_entry(key, out_key, exit))

    def _set_entry(self, key: object, out_key: object, exit: Exit[object, Issue]) -> None:
        value = self._value(key, exit)
        if out_key is _SKIPPED or value is _SKIPPED or value is MISSING:
            return
        # Declared keys belong to their properties, also after key decoding.
        if key not in self.declared and out_key not in self.declared:
            self.out[out_key] = value
