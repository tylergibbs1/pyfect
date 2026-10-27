"""The schema AST (Effect's ``SchemaAST``): one node per kind of value.

A schema object (``Bottom``) wraps one of these. Each node knows the text
of what it expects (``get_expected``, ``"string"``) and parses a value of
its own kind (``parse``), then runs its ``checks`` (``Filter`` /
``FilterGroup``) on the value. ``annotations`` hold documentation and
message overrides (``identifier``, ``message``, ``expected``, ...), keyed
in snake_case.

Python mappings: ``Number`` accepts ``int`` and ``float`` (JavaScript has one
number type), ``BigInt`` accepts ``int``, ``Null`` is ``None``; ``bool`` is
neither a number nor a bigint. ``Enum`` is a Python ``enum.Enum``, decoded
from its values. ``Undefined``, ``Void``, ``Symbol``, ``UniqueSymbol`` and
``ObjectKeyword`` have no Python counterpart (one ``None``, no symbols,
every value an object) and are not ported.
"""

from pyfect.schema.ast._base import (
    AST,
    Annotations,
    Checks,
    Refinement,
    annotate,
    append_checks,
    invalid_type,
    issue_of,
)
from pyfect.schema.ast._check import (
    Check,
    Filter,
    FilterGroup,
    FilterIssue,
    FilterOutput,
    collect_issues,
    filter_of,
    make_filter,
    make_filter_by_guard,
    normalize_filter_output,
)
from pyfect.schema.ast._keywords import (
    Any,
    BigInt,
    Boolean,
    Never,
    Null,
    Number,
    String,
    Unknown,
    any_,
    big_int,
    boolean,
    never,
    null,
    number,
    string,
    unknown,
)
from pyfect.schema.ast._literal import (
    Enum,
    EnumSide,
    Literal,
    LiteralValue,
    format_literal,
    same_literal,
)
from pyfect.schema.ast._union import Union, UnionMode

__all__ = [
    "AST",
    "Annotations",
    "Any",
    "BigInt",
    "Boolean",
    "Check",
    "Checks",
    "Enum",
    "EnumSide",
    "Filter",
    "FilterGroup",
    "FilterIssue",
    "FilterOutput",
    "Literal",
    "LiteralValue",
    "Never",
    "Null",
    "Number",
    "Refinement",
    "String",
    "Union",
    "UnionMode",
    "Unknown",
    "annotate",
    "any_",
    "append_checks",
    "big_int",
    "boolean",
    "collect_issues",
    "filter_of",
    "format_literal",
    "invalid_type",
    "issue_of",
    "make_filter",
    "make_filter_by_guard",
    "never",
    "normalize_filter_output",
    "null",
    "number",
    "same_literal",
    "string",
    "unknown",
]
