"""``Objects``: a mapping with declared keys (a struct) and key patterns (a
record), Effect's ``Objects``.

A ``PropertySignature`` is one declared key: required, optional (absent
from the output when absent from the input) or defaulted (a missing key
takes ``default()``, on the decoding side only). An ``IndexSignature``
takes every other key its ``parameter`` node accepts, with values of its
``type``. A key no signature takes is excess: dropped, or an
``UnexpectedKey`` under ``on_excess_property="error"``.

The input is any ``Mapping``; the output is a new ``dict``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, replace
from typing import cast

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, invalid_type, issue_of
from pyfect.schema.issue import Composite, Issue, MissingKey, Pointer, UnexpectedKey, reported


@dataclass(frozen=True, slots=True)
class PropertySignature:
    """A declared key ``name`` with values of ``type``."""

    name: Hashable
    type: AST
    optional: bool = False
    default: Callable[[], object] | None = None
    """Makes the decoded value of a missing key (a class field's default)."""


@dataclass(frozen=True, slots=True)
class IndexSignature:
    """Every key ``parameter`` accepts, with values of ``type``."""

    parameter: AST
    type: AST

    def selects(self, key: object) -> bool:
        """``key`` is a value of the parameter's encoded side."""
        return isinstance(self.parameter.flip().to_type().parse(key, {}), Success)


@dataclass(frozen=True, slots=True, eq=False)
class Objects(AST):
    """A mapping with ``properties`` and ``index_signatures``."""

    properties: tuple[PropertySignature, ...] = ()
    index_signatures: tuple[IndexSignature, ...] = ()
    tag = "Objects"

    def get_expected(self) -> str:
        return "object"

    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        if not isinstance(input, Mapping):
            return invalid_type(self, input, options)
        return _Run(self, cast("Mapping[object, object]", input), options).run()

    def _rebuild(self, f: Callable[[AST], AST], *, keep_defaults: bool) -> Objects:
        return replace(
            self,
            properties=tuple(
                replace(p, type=f(p.type))
                if keep_defaults
                else replace(
                    p, type=f(p.type), optional=p.optional or p.default is not None, default=None
                )
                for p in self.properties
            ),
            index_signatures=tuple(
                IndexSignature(f(i.parameter), f(i.type)) for i in self.index_signatures
            ),
        )

    def flip(self) -> Objects:
        # Defaults make decoded values: on the encoded side a defaulted key
        # is optional (Effect's ``withDecodingDefault``).
        return self._rebuild(lambda t: t.flip(), keep_defaults=False)

    def to_type(self) -> Objects:
        return self._rebuild(lambda t: t.to_type(), keep_defaults=True)


class _Stop(Exception):
    """Parsing stops: the first mismatch under ``errors="first"``."""


class _Defect(Exception):
    """A child's parse failed with something other than an issue."""

    def __init__(self, failure: Failure[Issue]) -> None:
        self.failure = failure


_SKIPPED = object()
"""A child's value that failed under ``errors="all"``."""


class _Run:
    """One parse of a mapping: the output so far and the issues found."""

    __slots__ = ("ast", "input", "issues", "options", "out")

    def __init__(self, ast: Objects, input: Mapping[object, object], options: ParseOptions) -> None:
        self.ast = ast
        self.input = input
        self.options = options
        self.out: dict[object, object] = {}
        self.issues: list[Issue] = []

    def run(self) -> Exit[object, Issue]:
        try:
            self._parse_all()
        except _Stop:
            pass
        except _Defect as defect:
            return defect.failure
        if self.issues:
            issues = self.issues
            return fail_exit(
                Composite(self.ast, (issues[0], *issues[1:]), reported(self.input, self.options))
            )
        return Success(self.out)

    def _parse_all(self) -> None:
        ast = self.ast
        declared = {p.name for p in ast.properties}
        if self.options.get("on_excess_property") == "error":
            for key, value in self.input.items():
                if key not in declared and not any(i.selects(key) for i in ast.index_signatures):
                    self._report(key, UnexpectedKey(ast, reported(value, self.options)))
        for prop in ast.properties:
            self._property(prop)
        for index in ast.index_signatures:
            for key in [k for k in self.input if index.selects(k)]:
                self._index(index, key, declared)

    def _report(self, key: object, issue: Issue) -> None:
        self.issues.append(Pointer((cast("Hashable", key),), issue))
        if self.options.get("errors") != "all":
            raise _Stop

    def _value(self, key: object, exit: Exit[object, Issue]) -> object:
        """The parsed value, or ``_SKIPPED`` once its issue is reported."""
        match exit:
            case Success(value):
                return value
            case failure:
                issue = issue_of(failure)
                if issue is None:
                    raise _Defect(failure)
                self._report(key, issue)
                return _SKIPPED

    def _property(self, prop: PropertySignature) -> None:
        name = prop.name
        if name in self.input:
            value = self._value(name, prop.type.parse(self.input[name], self.options))
            if value is not _SKIPPED:
                self.out[name] = value
        elif prop.default is not None:
            self.out[name] = prop.default()
        elif not prop.optional:
            self._report(name, MissingKey(prop.type.key_annotations))

    def _index(self, index: IndexSignature, key: object, declared: set[Hashable]) -> None:
        out_key = self._value(key, index.parameter.parse(key, self.options))
        value = self._value(key, index.type.parse(self.input[key], self.options))
        if out_key is _SKIPPED or value is _SKIPPED:
            return
        # Declared keys belong to their properties, also after key decoding.
        if key not in declared and out_key not in declared:
            self.out[out_key] = value
