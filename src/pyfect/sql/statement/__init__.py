"""SQL statements and fragments (Effect's ``effect/sql/Statement``).

A client (``SqlClient``) is a ``Constructor``: call it with SQL text and
values to get a ``Statement``, an effect that runs it::

    sql = yield from SqlClient()
    users = yield from sql("SELECT * FROM users WHERE id = {id}", id=user_id)

Python 3.13 has no tagged templates, so the text is a ``str.format``-style
template whose placeholders are always bound parameters (or fragments and
helpers placed as they are). The text must be a string literal: its type is
``LiteralString``, so pyright rejects text built at runtime, and
``sql.unsafe(text, params)`` is the one way to run such text. On Python
3.14, a t-string is accepted too: ``sql(t"... {user_id}")``.

- ``Fragment`` and its segments (``Literal``, ``Identifier``,
  ``Parameter``, ``ArrayHelper``, the record helpers, ``Custom``)
- ``and_``, ``or_``, ``csv``, ``join``, ``in_``, ``insert``, ``update``,
  ``update_values``: helpers, also on every constructor
- ``Compiler``, ``make_compiler``, ``make_compiler_sqlite``,
  ``default_escape``: rendering fragments for a dialect
- ``default_transforms``: renaming result columns (``fx.case`` has the
  usual renamings)
- ``CurrentTransformer``, ``SpanPropagationEnabled``: references that steer
  how statements run
"""

from pyfect.sql.statement._compiler import (
    Compiled,
    Compiler,
    CompilerOptions,
    Dialect,
    Placeholder,
    default_escape,
    make_compiler,
    make_compiler_sqlite,
)
from pyfect.sql.statement._segments import (
    ArrayHelper,
    Custom,
    Fragment,
    Helper,
    Identifier,
    Literal,
    Parameter,
    RecordInsertHelper,
    RecordUpdateHelper,
    RecordUpdateHelperSingle,
    Segment,
    SqlText,
    and_,
    array_helper,
    csv,
    custom,
    fragment,
    identifier,
    in_,
    insert,
    is_custom,
    is_fragment,
    is_segment,
    join,
    literal,
    or_,
    parameter,
    record_insert_helper,
    record_update_helper,
    record_update_helper_single,
    update,
    update_values,
)
from pyfect.sql.statement._statement import (
    Constructor,
    CurrentTransformer,
    SpanAttributes,
    SpanPropagationEnabled,
    Statement,
    Transformer,
    make,
    span_name,
    span_target,
)
from pyfect.sql.statement._transforms import (
    PrimitiveKind,
    RowTransforms,
    default_transforms,
    primitive_kind,
)

__all__ = [
    "ArrayHelper",
    "Compiled",
    "Compiler",
    "CompilerOptions",
    "Constructor",
    "CurrentTransformer",
    "Custom",
    "Dialect",
    "Fragment",
    "Helper",
    "Identifier",
    "Literal",
    "Parameter",
    "Placeholder",
    "PrimitiveKind",
    "RecordInsertHelper",
    "RecordUpdateHelper",
    "RecordUpdateHelperSingle",
    "RowTransforms",
    "Segment",
    "SpanAttributes",
    "SpanPropagationEnabled",
    "SqlText",
    "Statement",
    "Transformer",
    "and_",
    "array_helper",
    "csv",
    "custom",
    "default_escape",
    "default_transforms",
    "fragment",
    "identifier",
    "in_",
    "insert",
    "is_custom",
    "is_fragment",
    "is_segment",
    "join",
    "literal",
    "make",
    "make_compiler",
    "make_compiler_sqlite",
    "or_",
    "parameter",
    "primitive_kind",
    "record_insert_helper",
    "record_update_helper",
    "record_update_helper_single",
    "span_name",
    "span_target",
    "update",
    "update_values",
]
