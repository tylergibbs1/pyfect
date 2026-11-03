"""Config and data: Config, ConfigProvider, Redacted, Data, Brand, and the
structural-value modules (Equal, Hash, Equivalence, Order) that Python's
``==``, ``hash`` and ``key=`` functions replace. Option is in core A."""

from api_coverage import Cluster, Module

ISINSTANCE = "`TypeId` symbols and `is*` guards"
EQUAL = "Equal, Hash"
ORDER = "Order, Equivalence, Combiner, Reducer"
DATA = "Data.Class, TaggedEnum, Match, Predicate"
LITERALS = "`Config.Literal` / `Literals(literals, name)`"
CONTAINERS = "`Config.Array` / `Config.Record` over element schemas"

CONFIG = Module(
    "Config",
    "effect/src/Config.ts",
    ("pyfect.config", "pyfect.config:Config"),
    renamed={
        "Int": "pyfect.config.integer",
        "Date": "pyfect.config.date_time",
    },
    pythonic={
        "isConfig": (ISINSTANCE, "`isinstance(x, Config)`"),
        "Literals": (LITERALS, "`config.literal([...], name=)`"),
        "Array": (CONTAINERS, "`config.list_of(element, name)`"),
        "Record": (CONTAINERS, "`config.dict_of(value, name)`"),
    },
)

CONFIG_PROVIDER = Module(
    "ConfigProvider",
    "effect/src/ConfigProvider.ts",
    ("pyfect.config_provider", "pyfect.config_provider:ConfigProvider"),
    renamed={
        "makeValue": "pyfect.config_provider.Value",
        "makeRecord": "pyfect.config_provider.Record",
        "makeArray": "pyfect.config_provider.Array",
    },
)

REDACTED = Module(
    "Redacted",
    "effect/src/Redacted.ts",
    ("pyfect.redacted",),
    pythonic={
        "isRedacted": (ISINSTANCE, "`isinstance(x, Redacted)`"),
        "makeEquivalence": (ORDER, "`==` (compares the values)"),
    },
)

DATA_MODULE = Module(
    "Data",
    "effect/src/Data.ts",
    ("pyfect.errors",),
    renamed={
        "Error": "pyfect.errors.TaggedError",
        "TaggedError": "pyfect.errors.TaggedError",
    },
    pythonic={
        "Class": (DATA, "`@dataclass(frozen=True)`"),
        "TaggedClass": (DATA, "a frozen dataclass; the class is the tag"),
        "taggedEnum": (DATA, "a union of frozen dataclasses and `match`"),
    },
)

BRAND = Module(
    "Brand",
    "effect/src/Brand.ts",
    ("pyfect.brand", "pyfect.brand:Brand"),
)

EQUAL_MODULE = Module(
    "Equal",
    "effect/src/Equal.ts",
    (),
    pythonic={
        "symbol": (EQUAL, "`__eq__`"),
        "equals": (EQUAL, "`==`"),
        "makeCompareMap": (EQUAL, "`dict` (hash, then `==`)"),
        "makeCompareSet": (EQUAL, "`set` (hash, then `==`)"),
        "isEqual": (EQUAL, "every Python object has `__eq__`"),
        "asEquivalence": (EQUAL, "`operator.eq`"),
        "byReference": (EQUAL, "a class without `__eq__` (identity)"),
        "byReferenceUnsafe": (EQUAL, "a class without `__eq__` (identity)"),
    },
)

HASH = Module(
    "Hash",
    "effect/src/Hash.ts",
    (),
    pythonic={
        "symbol": (EQUAL, "`__hash__`"),
        "hash": (EQUAL, "`hash(x)`"),
        "random": (EQUAL, "`object.__hash__` (identity)"),
        "combine": (EQUAL, "`hash((a, b))`"),
        "optimize": (EQUAL, "CPython's own hash"),
        "isHash": (EQUAL, "`isinstance(x, Hashable)`"),
        "number": (EQUAL, "`hash(n)`"),
        "string": (EQUAL, "`hash(s)`"),
        "structureKeys": (EQUAL, "a frozen dataclass's `__hash__` over its fields"),
        "structure": (EQUAL, "a frozen dataclass's `__hash__`"),
        "array": (EQUAL, "`hash(tuple(items))`"),
    },
)

_EQUIVALENCES = {
    "make": "any `(a, b) -> bool`",
    "strictEqual": "`operator.is_` / `==`",
    "String": "`==`",
    "Number": "`==`",
    "Boolean": "`==`",
    "BigInt": "`==`",
    "combine": "`lambda a, b: f(a, b) and g(a, b)`",
    "combineAll": "`all(f(a, b) for f in fs)`",
    "mapInput": "`lambda a, b: f(key(a)) == f(key(b))`",
    "Tuple": "`==` on tuples",
    "Array": "`==` on lists and tuples",
    "Struct": "`==` on dataclasses and dicts",
    "Record": "`==` on dicts",
    "makeReducer": "`functools.reduce`",
    "Date": "`==` on `datetime`",
}

EQUIVALENCE = Module(
    "Equivalence",
    "effect/src/Equivalence.ts",
    (),
    pythonic={name: (ORDER, said) for name, said in _EQUIVALENCES.items()},
)

_ORDERS = {
    "make": "a `key=` function",
    "String": "`<` on `str`",
    "Number": "`<` on numbers",
    "Boolean": "`<` on `bool`",
    "BigInt": "`<` on `int`",
    "flip": "`reverse=True`",
    "combine": "a key returning a tuple",
    "alwaysEqual": "a constant key",
    "combineAll": "a key returning a tuple",
    "mapInput": "`key=`",
    "Date": "`<` on `datetime`",
    "Tuple": "`<` on tuples",
    "Array": "`<` on lists",
    "Struct": "a key returning a tuple of fields",
    "isLessThan": "`<`",
    "isGreaterThan": "`>`",
    "isLessThanOrEqualTo": "`<=`",
    "isGreaterThanOrEqualTo": "`>=`",
    "min": "`min(a, b, key=)`",
    "max": "`max(a, b, key=)`",
    "clamp": "`min(max(x, low), high)`",
    "isBetween": "`low <= x <= high`",
    "makeReducer": "`functools.reduce`",
}

ORDER_MODULE = Module(
    "Order",
    "effect/src/Order.ts",
    (),
    pythonic={name: (ORDER, said) for name, said in _ORDERS.items()},
)

CLUSTER = Cluster(
    "config-data",
    "Config and data (Config, ConfigProvider, Redacted, Data, Brand, Equal, Hash,"
    " Equivalence, Order)",
    (
        CONFIG,
        CONFIG_PROVIDER,
        REDACTED,
        DATA_MODULE,
        BRAND,
        EQUAL_MODULE,
        HASH,
        EQUIVALENCE,
        ORDER_MODULE,
    ),
)
