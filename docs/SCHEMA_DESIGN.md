# Schema typing design

How `pyfect.schema` (Effect v4's `Schema`) is typed, decided by the experiments
in `research/typing/schema_*.py` and pinned in `tests/type_checks.py` (the
`Schema` section). Later schema work keeps these pins green.

```python
from pyfect import schema as S
```

## The schema type

| Effect | pyfect |
|---|---|
| `Bottom<T, E, RD, RE, …>` (every schema object) | `S.Bottom[T, E = T, RD = Never, RE = Never]`, covariant in all four |
| `Codec<T, E, RD, RE>` (what a function takes) | `S.Codec[T, E, RD, RE]`: a protocol with one member, `__codec__()`, returning the `Bottom` |
| `Schema<T>`, `Decoder<T, RD>`, `Encoder<E, RE>`, `Top` | `S.Schema[T]`, `S.Decoder[T, RD]`, `S.Encoder[E, RE]`, `S.Top` (aliases of `Codec` with the other slots `object`) |
| `schema.ast` | `schema.ast`, a node of `S.ast` |

- A `Bottom` returns itself from `__codec__`. A schema *class* (`S.Class`, to
  come) returns `Bottom[Self, Mapping[str, object]]` from a `__codec__`
  classmethod, so `S.decode_unknown_sync(User)` works as in Effect. Anything
  taking a schema takes a `Codec` and reads `schema.__codec__()`.
- The synchronous adapters (`_sync`, `_exit`, `_option`, `_result`, `is_`)
  take `Codec[..., Never, ...]` in the services slot of their direction:
  a schema needing services is a type error there and works with `_effect`.
- Methods that would put a covariant parameter in an argument position use a
  method TypeVar and a self type (`make[A](self: Bottom[A, ...], input: A)`).

## Writing combinators

- Combining schemas: one shared TypeVar set, as in the runtime
  (`union(*members: Codec[A, I, R1, R2]) -> Bottom[A, I, R1, R2]`). Never
  `E1 | E2` of separately defaulted TypeVars.
- A curried combinator for `.pipe` that keeps a free TypeVar
  (`decode_to(to)` keeps the source's Encoded) must return an instance of a
  class with a generic `__call__`. A function returning a generic `Callable`
  is **not checked** by `.pipe` (`schema_1_codec.py`, Q5).
- Literals: `literals[L: LiteralString | int | bool | None](*values: L)`
  keeps string literals; all-int calls widen to `int` and need the expected
  type (`x: S.Bottom[Literal[1, 2], Literal[1, 2]] = S.Literals(1, 2)`).
- Brands: pyright reads a `NewType` passed as `Callable[[A], B]` as returning
  `Any`, so a brand names both types through `pyfect.brand.Brand[str, UserId]`:
  `S.String.pipe(S.from_brand(Brand[str, UserId].nominal()))` is
  `Bottom[UserId, str]`.

## Structs and classes (the decision for the Struct / Class work)

No spelling lets pyright compute a struct's Encoded type (there are no mapped
types), so structs and classes have the Encoded `Mapping[str, object]`
(`dict[str, object]` would reject TypedDicts and `dict[str, int]`, dict being
invariant). The Type is exact:

```python
class User(S.Class):  # dataclass_transform: __init__(*, id, name, ...)
    id: int  # the annotation is the Type; S.Int is derived
    name: str
    score: float = S.field(S.NumberFromString)  # checked: the schema's Type must fit float
    nick: str | None = None  # a default makes the key optional when decoding
```

- The annotation is the Type, and its schema is derived on first use (the
  first `__codec__()`, then cached), not when the class is made: at class
  creation a self or forward reference (`children: list[Node]`, Effect's
  `suspend`) is not bound yet and raises `NameError`. `str` String, `int` Int, `float` Number, `bool` Boolean, `None` Null,
  `object` Unknown, `Any` Any, `Literal[...]` Literals, `X | Y` Union,
  `list[X]` / `tuple[X, ...]` Array, `tuple[X, Y]` Tuple, `dict[str, X]`
  Record, an `Enum` Enum, a schema class itself. Anything else raises
  `TypeError` on that first use (a boundary error, not a parse error).
- `S.field(schema, default=...)` gives any other schema (checks,
  transformations). It is a `dataclass_transform` field specifier returning
  the schema's Type, so `wrong: str = S.field(S.Int)` is a type error. Its
  schema takes no services (`Codec[A, object, Never, Never]`).
- Effect's `Struct({...})` over an object literal becomes a TypedDict:
  `S.Struct(UserDict)` is `Bottom[UserDict, Mapping[str, object]]`, and
  `NotRequired[...]` is an optional key. A struct over a `dict` of schemas
  would widen every field to the union of all field types, so it is not
  offered.
- `Annotated[T, schema]` is not used for schemas: pyright cannot check the
  schema against `T`.

`S.Int` is the `int` schema with the messages of Effect's `Int` check;
`S.BigInt` is also `int`, with Effect's `bigint` messages.

## Runtime

- AST nodes (`S.ast`) are frozen dataclasses compared by identity, with
  keyword-only `annotations` (snake_case keys: `identifier`, `message`,
  `message_missing_key`, ...). Each implements `get_expected()` and
  `parse(input, options) -> Exit[object, Issue]`; a node without an encoding
  is its own `flip()` and `to_type()`.
- Issues (`S.issue`) are frozen dataclasses; `input` is `Some(value)` only
  under `report_input=True`. `format_issue` is Effect's default formatter.
- `ParseOptions` is a TypedDict passed as keyword arguments, both when an
  adapter is made and when it is called (call keys override). Effect's v3
  `exact` option does not exist in v4 and is rejected by the type.
- `SchemaError` is a `TaggedError` holding the issue; `str(error)` is the
  message (Effect prints `SchemaError(<message>)`).
- Deviations: `make` raises `SchemaError` (Effect throws an `Error` whose
  cause is the issue). A sync adapter meeting a defect raises
  `RuntimeError("<Kind> adapter can only ...")` chained from the defect.
  `Undefined`, `Void`, `Symbol`, `UniqueSymbol` and `ObjectKeyword` have no
  Python counterpart. The Promise adapters wait for effectful parsers.
