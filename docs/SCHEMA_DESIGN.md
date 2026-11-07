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
- Schema subclasses (`TupleSchema`, `OptionSchema`, ...) declare their
  TypeVars (`TypeVar("RD_co", covariant=True)`, `Generic[...]`) rather than
  using `class X[A, RD]` syntax: pyright infers a frozen dataclass's field
  parameters as invariant, so a schema needing no services would not fit a
  combinator that shares one `RD` (`TupleWithRest(Tuple(...), needs_db)`).
  Keys of a `dict` / `Mapping` stay invariant, as do the literals of
  `LiteralsSchema` (`pick` takes them). `tests/test_schema_variance.py`
  fails on a schema class with inferred variance.

## Writing combinators

- Combining schemas: one shared TypeVar set, as in the runtime
  (`union(*members: Codec[A, I, R1, R2]) -> Bottom[A, I, R1, R2]`). Never
  `E1 | E2` of separately defaulted TypeVars.
- A curried combinator for `.pipe` that keeps a free TypeVar
  (`decode_to(to)` keeps the source's Encoded) must return an instance of a
  class with a generic `__call__`. A function returning a generic `Callable`
  is **not checked** by `.pipe` (`schema_1_codec.py`, Q5).
- Literals: `Literals[L: LiteralString | int | float | bool | None](*values: L)`
  keeps string literals; all-int calls widen to `int` and need the expected
  type (`x: S.LiteralsSchema[Literal[1, 2]] = S.Literals(1, 2)`).
- Checks: `Filter[T]` / `FilterGroup[T]` are contravariant in `T`, so a
  check on `Sized` fits a `str` schema and a check on `float` does not.
  `schema.check(*checks)` keeps the schema's type; `S.refine(guard)` and
  `S.from_brand(brand)` change it and are curried classes for `.pipe`.
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
  `object` Unknown, `Any` Any, `Literal[x]` Literal, `Literal[x, y]`
  Literals, `X | Y` Union, `dict[K, V]` / `Mapping[K, V]` Record, a
  TypedDict a Struct, an `Enum` Enum, a schema class itself (`Annotated`,
  `NewType` and `type` aliases are unwrapped). `list[X]` List, `tuple[X, ...]` /
  `Sequence[X]` Array, `tuple[X, Y]` Tuple, `frozenset[X]` /
  `AbstractSet[X]` FrozenSet, `Redacted[X]` Redacted, `timedelta` Duration
  (a variadic `tuple[X, *tuple[Y, ...]]` needs `S.field(S.TupleWithRest(...))`). Anything else raises `TypeError` on that first
  use (a boundary error, not a parse error).
- `S.field(schema, default=...)` gives any other schema (checks,
  transformations). It is a `dataclass_transform` field specifier returning
  the schema's Type, so `wrong: str = S.field(S.Int)` is a type error. Its
  schema takes no services (`Codec[A, object, Never, Never]`).
  `S.field(schema, key="primaryKey")` (or `S.field(key=...)` alone, the schema
  coming from the annotation) gives the attribute another key on the wire: JSON,
  `SchemaBinary` identities and decode errors use it, the constructor's keyword
  stays the attribute.
- Effect's `Struct({...})` over an object literal becomes a TypedDict:
  `S.Struct(UserDict)` is `Bottom[UserDict, Mapping[str, object]]`, and
  `NotRequired[...]` is an optional key. A struct over a `dict` of schemas
  would widen every field to the union of all field types, so it is not
  offered.
- `Annotated[T, schema]` is not used for schemas: pyright cannot check the
  schema against `T`.
- A struct field takes another schema as a keyword: `S.Struct(UserDict,
  id=S.Int.check(...))`; a keyword naming no key of the TypedDict raises
  `TypeError`. A field schema may need services (`RD` / `RE` of the struct).
- `S.Record(key, value)` has the Type `dict[K, V]` and the Encoded
  `Mapping[KI, VI]`. Literal keys become required properties, any other key
  schema (an `Enum` too) an index signature; a key matching no index
  signature is excess.
- A missing key with a default decodes to the default (Effect's
  `withDecodingDefault`), so a defaulted field is optional when decoding
  and on the encoded side (a defaulted literal field is no union sentinel).
- A class decodes from a mapping only: an instance is not a mapping (Effect
  also takes an instance, a JavaScript object having its fields as keys).
- Construction is validation: `User(id=1)` runs the field schemas and the
  class checks and raises `SchemaError`; `User.make` takes an instance (it
  revalidates it). Class checks are methods decorated with
  `@S.class_check(**annotations)` returning `True`/`None`, `False` or a
  message. `S.Class(frozen=False)` makes a mutable class; `tag=` names a
  `TaggedClass`'s tag (default: the class name).
- `S.Error` / `S.TaggedError` are exceptions (`S.TaggedError` an
  `errors.TaggedError`, so `catch_tag` works): frozen fields, but `add_note`
  and the traceback stay writable; equal when their fields are.
- A union picks the members to try by tag: a member whose input is a
  mapping with required literal keys (`_tag: Literal["A"]`) is tried only
  when the input holds one of its values and contradicts none, and the
  union names it `{ readonly "_tag": "A", ... }` (Effect's sentinels). A
  suspended member is a candidate for any input and is not made to select
  candidates (it may be the union itself).

- Tagged unions: a case is a TypedDict struct with a `_tag: Literal["A"]`
  key (`S.TaggedStruct`) or a `TaggedClass`; `S.TaggedUnion(*cases)` /
  `S.to_tagged_union(tag)` keep `cases` / `guards` by literal, and a value
  is matched with Python's `match` statement, which pyright checks for
  exhaustiveness (`case {"_tag": "A"}:` for a TypedDict: a mapping pattern
  that also captures keys does not narrow). A guard is a `TypeGuard` of the
  whole union (no negative narrowing). Effect's `Opaque` is `S.Class`.
- `S.StructWithRest(struct, *records)` keeps the struct's TypedDict as its
  Type (TypedDicts are open); PEP 728's `extra_items=` types the other keys,
  and `S.Struct` reads it as an index signature over the undeclared keys.
- Errors in JSON decode to `S.ErrorInstance` (data, never a class the input
  names); `S.Defect()` decodes an error's JSON to one and any other JSON to itself, as a
  `Die` holds any value.

`S.Int` is the `int` schema with the messages of Effect's `Int` check: an
`int` within the safe integers. It takes `1.0`, as Effect's does, and gives `1`
(the decoded type is `int`). `S.is_int` is `Number.isSafeInteger`, and keeps a
`1.0`, as `S.Literal(1)` does: JavaScript has one number;
`S.BigInt` is also `int`, with Effect's `bigint` messages.

## Tuples and arrays

- `S.Tuple(a, b)` has exact overloads up to eight elements, so its Type
  and Encoded are `tuple[A, B]` / `tuple[I, J]`. With more elements, or
  any `optional_key` element (pyright has no optional tuple slot), it
  falls back to `tuple[A | B, ...]` of the joined element types.
- `S.TupleWithRest(schema, rest, *post)` has overloads for prefixes of up
  to three elements and zero or one post-rest element, typing as
  `tuple[A, *tuple[R, ...]]` / `tuple[A, *tuple[R, ...], P]`. A rest
  schema is a `Codec`, never an `OptionalKey`, so Effect's "An optional
  element cannot follow a rest element" is a type error, not a runtime one.
- An array's Encoded is `Sequence[I]` (a list or a tuple is taken); its
  Type is `tuple[A, ...]` (`S.Array`) or `list[A]` (`S.List`).

## Runtime

- AST nodes (`S.ast`) are frozen dataclasses compared by identity, with
  keyword-only `annotations` (snake_case keys: `identifier`, `message`,
  `message_missing_key`, ...) and `checks`. Each implements `get_expected()`
  and `_parse(input, options) -> Exit[object, Issue]`; `AST.parse` runs
  `_parse` and then the checks (a check that raises is a defect). Annotating
  a node with checks annotates its last check, as in Effect. A node without
  an encoding is its own `flip()` and `to_type()`.
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

## Variant schemas and models

Decided by `research/typing/model_1_variants.py`.

- A variant class (`S.model.Class`, a `S.variant_schema` toolkit's `Class`)
  is an `S.Class` of the default variant: annotated fields, the class's
  validation and subclassing. `Model.field(spec)` (a variant field, a
  variant struct, or a schema that may need services) is a field specifier
  returning the default variant's Type, so the annotation is checked
  against it. A field the default variant lacks is assigned without an
  annotation and is no dataclass field.
- Variant keys cannot be computed (no mapped types). `Model.Class[Insert,
  Update, Json, JsonCreate, JsonUpdate]` takes TypedDicts, read back by
  non-data descriptors whose `__get__` solves the owner's type arguments
  (`User.insert: VariantStructSchema[UserInsert]`); when the class is made,
  each TypedDict must have the variant's keys, `NotRequired` only for a key
  with a constructor default. Without arguments a variant is
  `Mapping[str, object]`.
- An extracted variant is a `VariantStructSchema[TD]` (a `StructSchema`
  whose Encoded is `Mapping[str, object]`), whose `make` / `make_effect`
  fill constructor defaults (`with_constructor_default`, `Overrideable`).
- `sql.model.make_repository(User, ...)` reads `User.__model_variants__()`
  (`ModelVariants[Self, Insert, Update]`) through a protocol, so the
  repository is `Repository[User, UserInsert, UserUpdate]`.

