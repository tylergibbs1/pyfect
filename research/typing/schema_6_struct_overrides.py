"""Question: can ``Struct(TypedDict, key=schema)`` check, at type level, that
each keyword's schema decodes to the type the TypedDict gives that key?

Q1. ``**fields: Unpack[TD]`` with ``TD`` a TypeVar solved from ``type[TD]``?
Q2. A ``ParamSpec`` captured from the TypedDict's constructor, with a field
    specifier ``field(schema) -> T`` in place of each schema?
Q3. A keyword typed ``Codec[object, ...]`` (what ``Struct`` takes): what does
    a wrong schema give?

Run: ``uv run pyright -p research/typing research/typing/schema_6_struct_overrides.py``.

Answers:

Q1. No: ``TypedDict`` is no bound for a TypeVar and ``Unpack`` takes a TypedDict class, not a TypeVar (errors at the
    definition), and the keyword values would have the key's own type, not a
    schema of it. No mapped type turns ``TD`` into ``{key: Codec[TD[key]]}``.
Q2. No: a TypedDict class's constructor is an overload (a mapping, or the
    keys as keywords), which a ``ParamSpec`` does not match. Even matched, it
    would copy which keys are required, so a struct overriding one key would
    repeat all the others.
Q3. Accepted: the schema's decoded type is erased to ``object``. So
    ``Struct`` checks the given schema against the key's annotation when the
    struct is made (``pyfect/schema/_assignable.py``), a ``TypeError`` at
    import time instead of a pyright error.
"""

from collections.abc import Callable
from typing import Any, TypedDict, Unpack

from pyfect import schema as S


class Line(TypedDict):
    sku: str
    quantity: int


# Q1
def struct_unpack[TD: TypedDict](  # pyright: ignore[reportInvalidTypeForm]
    typed_dict: type[TD],
    **fields: Unpack[TD],  # pyright: ignore[reportGeneralTypeIssues]
) -> None: ...


# Q2
def field[T](schema: S.Codec[T, Any, Any, Any]) -> T: ...


def struct_spec[**P](
    typed_dict: Callable[P, object], *args: P.args, **fields: P.kwargs
) -> None: ...


struct_spec(Line, sku=field(S.String), quantity=field(S.Int))  # pyright: ignore[reportArgumentType]

# Q3
S.Struct(Line, quantity=S.NumberFromString)  # no error; a TypeError when run
