"""Schema family: Schema, SchemaAST, SchemaGetter, SchemaTransformation,
SchemaIssue, SchemaParser, SchemaRepresentation and JsonSchema. The
JSON Schema, Standard Schema, arbitrary, equivalence and formatter parts
are exports of ``Schema.ts``. ``StandardSchema.ts`` exports only types."""

from api_coverage import Cluster, Module

ISINSTANCE = "`TypeId` symbols and `is*` guards"
NO_UNDEFINED = "`Schema.Undefined`, `Void`, `Symbol`"
OPTIONAL = "`Schema.UndefinedOr` / `NullishOr`"
PROMISE = "`Schema.decodePromise` / `encodePromise`"
TYPE_LEVEL = "`Schema.mutable`, `mutableKey` / `readonlyKey`"
METHODS = "`Schema.annotate` / `annotateKey`"
COLLECTIONS = "`ReadonlySet` / `HashSet`, `ReadonlyMap` / `HashMap`, `Chunk`"
OPAQUE = "`Schema.Opaque<Self>()(struct)`"
STANDARD = "| StandardSchema |"

_UNDEFINED_NAMES = ("Undefined", "Void", "Symbol", "UniqueSymbol", "ObjectKeyword")

SCHEMA = Module(
    "Schema",
    "effect/src/Schema.ts",
    ("pyfect.schema", "pyfect.schema:Bottom"),
    renamed={
        "Uint8Array": "pyfect.schema.Bytes",
        "Uint8ArrayFromBase64": "pyfect.schema.BytesFromBase64",
        "Uint8ArrayFromBase64Url": "pyfect.schema.BytesFromBase64Url",
        "Uint8ArrayFromHex": "pyfect.schema.BytesFromHex",
    },
    pythonic={
        "isSchemaError": (ISINSTANCE, "`isinstance(x, SchemaError)`"),
        **{name: (NO_UNDEFINED, "not ported") for name in _UNDEFINED_NAMES},
        "isStringSymbol": (NO_UNDEFINED, "not ported"),
        "PropertyKey": (NO_UNDEFINED, "`S.String` / `S.Number` keys"),
        "UndefinedOr": (OPTIONAL, "`S.NullOr`"),
        "NullishOr": (OPTIONAL, "`S.NullOr`"),
        "OptionFromUndefinedOr": (OPTIONAL, "`S.OptionFromNullOr`"),
        "OptionFromNullishOr": (OPTIONAL, "`S.OptionFromNullOr`"),
        "OptionFromOptional": (OPTIONAL, "`S.OptionFromOptionalKey`"),
        "requiredKey": (OPTIONAL, "a key is required unless `S.optional_key`"),
        "optional": (OPTIONAL, "`S.optional_key`"),
        "required": (OPTIONAL, "a key is required unless `S.optional_key`"),
        "withDecodingDefault": (OPTIONAL, "`S.with_decoding_default_key`"),
        "withDecodingDefaultType": (OPTIONAL, "`S.with_decoding_default_type_key`"),
        "decodeUnknownPromise": (PROMISE, "`run_async(S.decode_unknown_effect(s)(x))`"),
        "decodePromise": (PROMISE, "`run_async(S.decode_effect(s)(x))`"),
        "encodeUnknownPromise": (PROMISE, "`run_async(S.encode_unknown_effect(s)(x))`"),
        "encodePromise": (PROMISE, "`run_async(S.encode_effect(s)(x))`"),
        "mutable": (TYPE_LEVEL, "`S.List`"),
        "mutableKey": (TYPE_LEVEL, "not ported"),
        "readonlyKey": (TYPE_LEVEL, "not ported"),
        "revealBottom": (TYPE_LEVEL, "not ported"),
        "revealCodec": (TYPE_LEVEL, "not ported"),
        "StringForLiteralAutocomplete": (TYPE_LEVEL, "not ported"),
        "brand": (METHODS, "`S.from_brand(brand)`"),
        "ReadonlyMap": (COLLECTIONS, "`S.Map`"),
        "ReadonlySet": (COLLECTIONS, "`S.FrozenSet`"),
        "HashMap": (COLLECTIONS, "`S.Map`"),
        "HashSet": (COLLECTIONS, "`S.FrozenSet`"),
        "Chunk": (COLLECTIONS, "`S.Array`"),
        "Opaque": (OPAQUE, "`class Self(S.Class)`"),
        "toStandardSchemaV1": (STANDARD, "the pydantic adapter"),
        "toStandardJSONSchemaV1": (STANDARD, "the pydantic adapter"),
        "StandardSchemaV1FailureResult": (STANDARD, "the pydantic adapter"),
    },
)
AST = Module(
    "SchemaAST",
    "effect/src/SchemaAST.ts",
    ("pyfect.schema.ast",),
    renamed={"optional": "pyfect.schema.ast.optional_key"},
    pythonic={
        **{
            name: (ISINSTANCE, f"`isinstance(ast, {name.removeprefix('is')})`")
            for name in (
                "isAST",
                "isDeclaration",
                "isNull",
                "isNever",
                "isUnknown",
                "isAny",
                "isString",
                "isNumber",
                "isBoolean",
                "isBigInt",
                "isLiteral",
                "isEnum",
                "isTemplateLiteral",
                "isArrays",
                "isObjects",
                "isUnion",
                "isSuspend",
            )
        },
        **{
            name: (NO_UNDEFINED, "not ported")
            for name in (
                "isUndefined",
                "isVoid",
                "isSymbol",
                "isUniqueSymbol",
                "isObjectKeyword",
                "Undefined",
                "undefined",
                "Void",
                "void",
                "ObjectKeyword",
                "objectKeyword",
                "UniqueSymbol",
                "Symbol",
                "symbol",
                "isStringSymbol",
                "symbolString",
                "objectKeywordToJson",
            )
        },
        "mutable": (TYPE_LEVEL, "not ported"),
        "mutableKey": (TYPE_LEVEL, "not ported"),
        "isMutable": (TYPE_LEVEL, "not ported"),
    },
)
GETTER = Module("SchemaGetter", "effect/src/SchemaGetter.ts", ("pyfect.schema.getter",))
TRANSFORMATION = Module(
    "SchemaTransformation",
    "effect/src/SchemaTransformation.ts",
    ("pyfect.schema.transformation",),
    renamed={
        "bigintFromString": "pyfect.schema.transformation.big_int_from_string",
        "uint8ArrayFromBase64String": "pyfect.schema.transformation.bytes_from_base64_string",
        "optionFromOptional": "pyfect.schema.transformation.option_from_optional_key",
    },
    pythonic={
        "optionFromUndefinedOr": (OPTIONAL, "`option_from_null_or`"),
        "optionFromNullishOr": (OPTIONAL, "`option_from_null_or`"),
    },
)
ISSUE = Module("SchemaIssue", "effect/src/SchemaIssue.ts", ("pyfect.schema.issue",))
PARSER = Module(
    "SchemaParser",
    "effect/src/SchemaParser.ts",
    ("pyfect.schema",),
    pythonic={
        name: (PROMISE, "`run_async` of the `_effect` form")
        for name in (
            "decodeUnknownPromise",
            "decodePromise",
            "encodeUnknownPromise",
            "encodePromise",
        )
    },
)
REVIVED_SCHEMAS = "`SchemaRepresentation` revivers of schemas pyfect has not ported"

REPRESENTATION = Module(
    "SchemaRepresentation",
    "effect/src/SchemaRepresentation.ts",
    ("pyfect.schema.representation",),
    renamed={
        "ReadonlyMapReviver": "pyfect.schema.representation.map_reviver",
        "ReadonlySetReviver": "pyfect.schema.representation.frozen_set_reviver",
        "Uint8ArrayReviver": "pyfect.schema.representation.bytes_reviver",
    },
    pythonic={
        "isStringSymbolReviver": (NO_UNDEFINED, "not ported"),
        "HashMapReviver": (COLLECTIONS, "`map_reviver`"),
        "HashSetReviver": (COLLECTIONS, "`frozen_set_reviver`"),
        "ChunkReviver": (COLLECTIONS, "an array needs no reviver"),
        **{
            name: (REVIVED_SCHEMAS, "not ported")
            for name in (
                "DateReviver",
                "FileReviver",
                "FormDataReviver",
                "URLSearchParamsReviver",
                "GraphReviver",
            )
        },
    },
)
JSON_SCHEMA = Module(
    "JsonSchema",
    "effect/src/JsonSchema.ts",
    ("pyfect.json_schema",),
    renamed={
        "fromSchemaDraft07": "pyfect.json_schema.from_schema_draft_07",
        "fromSchemaDraft2020_12": "pyfect.json_schema.from_schema_draft_2020_12",
        "fromSchemaOpenApi3_1": "pyfect.json_schema.from_schema_open_api_3_1",
        "fromSchemaOpenApi3_0": "pyfect.json_schema.from_schema_open_api_3_0",
        "toDocumentDraft07": "pyfect.json_schema.to_document_draft_07",
        "toDocumentDraft04": "pyfect.json_schema.to_document_draft_04",
        "toMultiDocumentOpenApi3_1": "pyfect.json_schema.to_multi_document_open_api_3_1",
    },
)

CLUSTER = Cluster(
    "schema",
    "Schema family",
    (SCHEMA, AST, GETTER, TRANSFORMATION, ISSUE, PARSER, REPRESENTATION, JSON_SCHEMA),
)
