"""Construction through the compiler registry (Effect's
``makeConstructorSync``, ``makeClassSync`` and ``makeEffect``): an installed
synchronous ``make`` first, then the complete ``make_effect``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Never, cast

from pyfect.cause import die as die_cause
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._adapters import CONSTRUCTOR, raise_schema_failure, schema_error_of
from pyfect.schema._error import SchemaError
from pyfect.schema._options import ParseOptions, constructing
from pyfect.schema.ast import AST, Class, ParseResult, check_instance
from pyfect.schema.ast._result import MISSING, flat_map, run_now
from pyfect.schema.compiler import _registry
from pyfect.schema.compiler._registry import DEFAULT_PARSE_OPTIONS, INVALID
from pyfect.schema.issue import InvalidValue, Issue


def _present(value: object) -> Exit[object, Issue]:
    # A root constructor never gives back an absent value.
    return fail_exit(InvalidValue()) if value is MISSING else Success(value)


class Maker:
    """The constructor of a type-side AST, its entry resolved on first use
    and kept."""

    __slots__ = ("_entry", "ast")

    def __init__(self, ast: AST) -> None:
        self.ast = ast
        self._entry: _registry.Entry | None = None

    @classmethod
    def of(cls, entry: _registry.Entry) -> Maker:
        """The constructor of an entry already resolved."""
        maker = cls(entry.ast)
        maker._entry = entry
        return maker

    def entry(self) -> _registry.Entry:
        if self._entry is None:
            self._entry = _registry.resolve(self.ast)
        return self._entry

    def parse(self, input: object, options: ParseOptions, fast: bool) -> ParseResult:
        """``input`` constructed: by ``make`` when ``fast`` and installed,
        else (or after ``INVALID``) by ``make_effect``."""
        entry = self.entry()
        if not _registry.active():
            return _settled(self.ast.parse(input, constructing(options)))
        plain = options or DEFAULT_PARSE_OPTIONS
        if fast and input is not MISSING:
            make = entry.make
            if make is not None:
                try:
                    output = make(input, plain)
                except Exception as defect:
                    _constructor_defect(defect)
                if output is not INVALID and output is not MISSING:
                    return Success(output)
        return _settled(entry.make_effect(input, constructing(options)))


def _settled(result: ParseResult) -> ParseResult:
    if type(result) is Success:
        return _present(result.value)
    if isinstance(result, Failure):
        return result
    return flat_map(result, _present)


def _constructor_defect(defect: Exception) -> Never:
    """A constructor that raised: ``RuntimeError(CONSTRUCTOR)`` from the defect (Effect's
    ``throwConstructorDefect``, an ``Error`` whose cause is ``Cause.die(defect)``)."""
    schema_error_of(die_cause(defect), CONSTRUCTOR)
    raise AssertionError("unreachable")  # pragma: no cover


def _construct_sync(entry: _registry.Entry, input: object, options: ParseOptions) -> object:
    match run_now(Maker.of(entry).parse(input, options, True)):
        case Success(value):
            return value
        case failure:
            raise_schema_failure(failure.cause.map(SchemaError), CONSTRUCTOR)


def make_class_sync[T](
    ast: AST,
    input: object,
    options: ParseOptions | None,
    construct: Callable[[Mapping[object, object]], T],
) -> T:
    """A class instance made from its type side (Effect's ``SchemaParser.makeClassSync``):
    an installed ``make`` / ``make_effect`` makes it; otherwise an instance is kept as it
    is, and plain fields are checked by the fields' constructor (resolved through the
    class's entry) and handed to ``construct``, a raise there being a constructor defect;
    the class's own checks then run on the instance."""
    entry = _registry.resolve(ast)
    plain = options or DEFAULT_PARSE_OPTIONS
    if (
        not isinstance(ast, Class)
        or entry.make is not None
        or entry.compiled_make_effect is not None
    ):
        return cast("T", _construct_sync(entry, input, plain))
    shape = ast.shape
    if isinstance(input, shape.cls):
        return cast("T", input)
    fields = _construct_sync(entry.resolve(shape.fields.to_type()), input, plain)
    try:
        instance = construct(cast("Mapping[object, object]", fields))
    except Exception as defect:
        _constructor_defect(defect)
    match check_instance(shape, instance, plain):
        case Success():
            return instance
        case failure:
            raise_schema_failure(failure.cause.map(SchemaError), CONSTRUCTOR)
