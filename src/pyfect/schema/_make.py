"""Construction through the compiler registry (Effect's
``makeConstructorSync`` and ``makeEffect``): an installed synchronous
``make`` first, then the complete ``make_effect``."""

from __future__ import annotations

from pyfect.cause import die as die_cause
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._adapters import CONSTRUCTOR, schema_error_of
from pyfect.schema._options import ParseOptions, constructing
from pyfect.schema.ast import AST, ParseResult
from pyfect.schema.ast._result import MISSING, flat_map
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
                    schema_error_of(die_cause(defect), CONSTRUCTOR)
                    raise
                if output is not INVALID and output is not MISSING:
                    return Success(output)
        return _settled(entry.make_effect(input, constructing(options)))


def _settled(result: ParseResult) -> ParseResult:
    if type(result) is Success:
        return _present(result.value)
    if isinstance(result, Failure):
        return result
    return flat_map(result, _present)
