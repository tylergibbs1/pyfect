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

The input is any ``Mapping``; the output is a new ``dict``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, replace
from typing import cast, final

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import (
    AST,
    at_key,
    construct_missing,
    invalid_type,
    issue_of,
    join_checks,
)
from pyfect.schema.ast._result import MISSING, ParseResult
from pyfect.schema.ast._steps import Abort, Pending, Steps, Stop, Suspended, run_steps
from pyfect.schema.ast._suspend import Suspend
from pyfect.schema.issue import Composite, Issue, MissingKey, Pointer, UnexpectedKey, reported


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

    def optional_when_encoded(self) -> bool:
        """Whether the key may be missing from the encoded input."""
        if self.encoded_optional is not None:
            return self.encoded_optional
        return self.optional or self.default is not None or self.type.flip().optional_key

    def flipped(self) -> PropertySignature:
        type = self.type.flip()
        return PropertySignature(self.name, type, self.optional_when_encoded(), None, self.optional)


@dataclass(frozen=True, slots=True)
class IndexSignature:
    """Every key ``parameter`` accepts, with values of ``type``."""

    parameter: AST
    type: AST

    def selects(self, key: object, options: ParseOptions | None = None) -> bool:
        """``key`` is a value of the parameter's encoded side."""
        return type(self.parameter.flip().to_type().parse(key, options or {})) is Success


@dataclass(frozen=True, slots=True, eq=False)
class Objects(AST):
    """A mapping with ``properties`` and ``index_signatures``."""

    properties: tuple[PropertySignature, ...] = ()
    index_signatures: tuple[IndexSignature, ...] = ()
    tag = "Objects"

    def get_expected(self) -> str:
        return "object"

    def _parse(self, input: object, options: ParseOptions) -> ParseResult:
        if not isinstance(input, Mapping):
            return invalid_type(self, input, options)
        run = _Run(self, cast("Mapping[object, object]", input), options)
        return run_steps(run, options.get("concurrency"))

    def _flip(self) -> Objects:
        # Checks describe the decoded side: flipped, they check the input
        # (Effect swaps ``checks`` and ``encodingChecks``).
        return replace(
            self,
            properties=tuple(p.flipped() for p in self.properties),
            index_signatures=tuple(
                IndexSignature(i.parameter.flip(), i.type.flip()) for i in self.index_signatures
            ),
            checks=self.encoding_checks,
            encoding_checks=self.checks,
        )

    def _to_type(self) -> Objects:
        properties = tuple(replace(p, type=p.type.to_type()) for p in self.properties)
        indexes = tuple(
            IndexSignature(i.parameter.to_type(), i.type.to_type()) for i in self.index_signatures
        )
        same = all(
            a.type is b.type for a, b in zip(properties, self.properties, strict=True)
        ) and all(
            a.parameter is b.parameter and a.type is b.type
            for a, b in zip(indexes, self.index_signatures, strict=True)
        )
        if same and self.encoding_checks is None:
            return self
        # Encoded and decoded values are the same when no part transforms:
        # the encoded side's checks then hold for the decoded one too.
        checks = join_checks(self.checks, self.encoding_checks) if same else self.checks
        return replace(
            self,
            properties=properties,
            index_signatures=indexes,
            checks=checks,
            encoding_checks=None,
        )


_SKIPPED = object()
"""A child's value that failed under ``errors="all"``."""


_NO_KEYS: frozenset[Hashable] = frozenset()
_NO_ENTRIES: tuple[tuple[IndexSignature, object], ...] = ()


@final
class _Run(Steps["_Run"]):
    """One parse of a mapping: the output so far and the issues found.
    Steps: the excess-key check, then each property, then each key an
    index signature selects."""

    __slots__ = ("ast", "declared", "entries", "input", "issues", "options", "out")

    def __init__(self, ast: Objects, input: Mapping[object, object], options: ParseOptions) -> None:
        self.ast = ast
        self.input = input
        self.options = options
        self.out: dict[object, object] = {}
        self.issues: list[Issue] = []
        if ast.index_signatures:
            self.declared: frozenset[Hashable] = frozenset(p.name for p in ast.properties)
            self.entries: tuple[tuple[IndexSignature, object], ...] = tuple(
                (i, key) for i in ast.index_signatures for key in input if i.selects(key, options)
            )
        else:
            self.declared, self.entries = _NO_KEYS, _NO_ENTRIES

    def copy(self) -> _Run:
        other = _Run.__new__(_Run)
        other.ast, other.input, other.options = self.ast, self.input, self.options
        other.entries, other.declared = self.entries, self.declared
        other.out = dict(self.out)
        other.issues = list(self.issues)
        return other

    def size(self) -> int:
        return 1 + len(self.ast.properties) + len(self.entries)

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
        input, options, out = self.input, self.options, self.out
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
        entries = self.entries
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
        for key, value in self.input.items():
            if key not in declared and not any(
                i.selects(key, self.options) for i in ast.index_signatures
            ):
                self._report(key, UnexpectedKey(ast, reported(value, self.options)))

    def _report(self, key: object, issue: Issue) -> None:
        self.issues.append(Pointer((cast("Hashable", key),), issue))
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
        if prop.type.encoding is not None or isinstance(prop.type, Suspend):
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
        result = index.type.parse(self.input[key], self.options)
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
