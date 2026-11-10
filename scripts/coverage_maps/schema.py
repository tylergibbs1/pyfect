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
COLLECTIONS = "`ReadonlySet`, `ReadonlyMap`, `Chunk`"
OPAQUE = "`Schema.Opaque<Self>()(struct)`"
INTERNAL = "Effect's `@internal` schema exports"
CONTEXT = "`SchemaAST.Context`"
DATE = "`Schema.Date`, `DateFromString`, `DateFromMillis`"
WEB = "`Schema.File`, `FormData`, `URLSearchParams`"
FIELDS_ASSIGN = "`Schema.fieldsAssign`"
HTTP = "pyfect.http.schema"
_CRYPTO_KEYS = tuple(
    f"{family}{suffix}"
    for family, suffixes in (
        ("MacKey", ("", "FromBytes", "FromFormat")),
        ("AeadKey", ("", "FromBytes", "FromFormat")),
        ("CipherKey", ("", "FromBytes", "FromFormat")),
        ("SignaturePublicKey", ("", "FromBytes", "FromFormat")),
        ("SignaturePrivateKey", ("", "FromBytes", "FromFormat")),
        ("KeyAgreementPublicKey", ("", "FromBytes", "FromFormat")),
        ("KeyAgreementPrivateKey", ("", "FromBytes", "FromFormat")),
        ("KeyWrapKey", ("", "FromBytes", "FromFormat")),
        ("KeyWrapPublicKey", ("", "FromFormat")),
        ("KeyWrapPrivateKey", ("", "FromFormat")),
    )
    for suffix in suffixes
)

_UNDEFINED_NAMES = ("Symbol", "UniqueSymbol")

SCHEMA = Module(
    "Schema",
    "effect/src/Schema.ts",
    ("pyfect.schema", "pyfect.schema:Bottom"),
    renamed={
        "Uint8Array": "pyfect.schema.Bytes",
        "Uint8ArrayFromBase64": "pyfect.schema.BytesFromBase64",
        "Uint8ArrayFromBase64Url": "pyfect.schema.BytesFromBase64Url",
        "Uint8ArrayFromHex": "pyfect.schema.BytesFromHex",
        "catchDecodingWithContext": "pyfect.schema.catch_decoding",
        "make": "pyfect.schema.Bottom",
        "catchEncodingWithContext": "pyfect.schema.catch_encoding",
        "toRepresentation": "pyfect.schema.representation.to_representation",
        **{
            name: f"{HTTP}.{name}"
            for name in (
                "DateTimeUtcFromHttpDate",
                "Cookie",
                "Cookies",
                "RecordFromCookies",
                "Headers",
                "RetryAfter",
                "RetryAfterFromString",
                "UrlParams",
                "JsonFromUrlParamsField",
                "RecordFromUrlParams",
            )
        },
        **{name: f"pyfect.crypto.schema.{name}" for name in _CRYPTO_KEYS},
    },
    pythonic={
        "isSchemaError": (ISINSTANCE, "`isinstance(x, SchemaError)`"),
        **{
            name: (INTERNAL, "not public")
            for name in ("withArrayLengthConstraints", "linkDecoding", "makeClassTrusted")
        },
        "fieldsAssign": (FIELDS_ASSIGN, "TypedDict inheritance"),
        "MutableJson": (TYPE_LEVEL, "`S.Json`"),
        "Date": (DATE, "`S.DateTimeUtc`"),
        "DateFromString": (DATE, "`S.DateTimeUtcFromString`"),
        "DateFromMillis": (DATE, "`S.DateTimeUtcFromMillis`"),
        **{
            name: (WEB, "`pyfect.http.schema.UrlParams` / `RecordFromUrlParams`")
            for name in (
                "File",
                "FormData",
                "fromFormData",
                "URLSearchParams",
                "fromURLSearchParams",
            )
        },
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
        "Chunk": (COLLECTIONS, "`S.Array`"),
        "Opaque": (OPAQUE, "`class Self(S.Class)`"),
    },
)
AST = Module(
    "SchemaAST",
    "effect/src/SchemaAST.ts",
    ("pyfect.schema.ast", "pyfect.schema.ast:AST"),
    renamed={
        "optional": "pyfect.schema.ast.optional_key",
        "isPattern": "pyfect.schema.is_pattern",
        "isStringFinite": "pyfect.schema.is_string_finite",
        "isStringBigInt": "pyfect.schema.is_string_big_int",
        "getContextOwner": "pyfect.schema.ast.AST.owner",
        "middlewareDecoding": "pyfect.schema.middleware_decoding",
        "middlewareEncoding": "pyfect.schema.middleware_encoding",
        "annotateKey": "pyfect.schema.Bottom.annotate_key",
    },
    pythonic={
        "Context": (
            CONTEXT,
            "the node fields `optional_key`, `key_annotations`, `constructor_default`",
        ),
        **{
            name: (INTERNAL, "not public")
            for name in (
                "defaultParseOptions",
                "templateLiteralParser",
                "stepArray",
                "parseArray",
                "getIndexSignatureKeys",
                "stepProperty",
                "parseProperties",
                "getAST",
                "collectSentinels",
                "getCandidateIndex",
                "isFinite",
                "finite",
                "replaceEncoding",
                "getLastEncoding",
                "replaceChecks",
                "mapLink",
                "applyToLastLink",
                "replaceContextLastLink",
                "applyToSelfOrLastLinkEncoding",
                "applyToSelfOrLastLinkEncodingIdempotent",
                "mapOrSame",
                "parameterFromPropertyKey",
                "parameterFromString",
                "bigIntString",
                "runChecks",
                "getConstructorDescriptor",
                "MutableJson",
                "unknownToJson",
                "unknownToStringTree",
            )
        },
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
                "isSymbol",
                "isUniqueSymbol",
                "UniqueSymbol",
                "Symbol",
                "symbol",
                "isStringSymbol",
                "symbolString",
            )
        },
        **{
            name: (NO_UNDEFINED, f"a `Declaration`, the schema `S.{schema}`")
            for name, schema in (
                ("isUndefined", "Undefined"),
                ("isVoid", "Void"),
                ("isObjectKeyword", "ObjectKeyword"),
                ("Undefined", "Undefined"),
                ("undefined", "Undefined"),
                ("Void", "Void"),
                ("void", "Void"),
                ("ObjectKeyword", "ObjectKeyword"),
                ("objectKeyword", "ObjectKeyword"),
                ("objectKeywordToJson", "ObjectKeyword"),
            )
        },
        "mutable": (TYPE_LEVEL, "not ported"),
        "mutableKey": (TYPE_LEVEL, "not ported"),
        "isMutable": (TYPE_LEVEL, "not ported"),
    },
)
GETTER = Module(
    "SchemaGetter",
    "effect/src/SchemaGetter.ts",
    ("pyfect.schema.getter", "pyfect.schema.getter:Getter"),
    pythonic={
        "Date": (DATE, "`date_time_utc_from_input`"),
        **{
            name: (WEB, "`pyfect.http.schema.RecordFromUrlParams`")
            for name in (
                "decodeFormData",
                "encodeFormData",
                "decodeURLSearchParams",
                "encodeURLSearchParams",
            )
        },
    },
)
TRANSFORMATION = Module(
    "SchemaTransformation",
    "effect/src/SchemaTransformation.ts",
    ("pyfect.schema.transformation",),
    renamed={
        "bigintFromString": "pyfect.schema.transformation.big_int_from_string",
        "uint8ArrayFromBase64String": "pyfect.schema.transformation.bytes_from_base64_string",
        "optionFromOptional": "pyfect.schema.transformation.option_from_optional_key",
        "makeTransformation": "pyfect.schema.transformation.Transformation",
        "composeTransformation": "pyfect.schema.transformation.Transformation.compose",
    },
    pythonic={
        "dateFromString": (DATE, "`date_time_utc_from_string`"),
        "dateFromMillis": (DATE, "`S.DateTimeUtcFromMillis`"),
        **{name: (INTERNAL, "not public") for name in ("errorFromJsonError", "defectFromJson")},
        **{
            name: (WEB, "`pyfect.http.schema.RecordFromUrlParams`")
            for name in ("fromFormData", "fromURLSearchParams")
        },
        "optionFromUndefinedOr": (OPTIONAL, "`option_from_null_or`"),
        "optionFromNullishOr": (OPTIONAL, "`option_from_null_or`"),
    },
)
ISSUE = Module(
    "SchemaIssue",
    "effect/src/SchemaIssue.ts",
    ("pyfect.schema.issue",),
    renamed={
        "normalizeFilterOutput": "pyfect.schema.ast.normalize_filter_output",
        "defaultLeafHook": "pyfect.schema.issue.leaf_message",
        "defaultFormatter": "pyfect.schema.issue.format_issue",
    },
    pythonic={name: (INTERNAL, "not public") for name in ("makeCompositeAtKey", "makeSingle")},
)
PARSER = Module(
    "SchemaParser",
    "effect/src/SchemaParser.ts",
    ("pyfect.schema", "pyfect.schema:Bottom"),
    pythonic={
        **{
            name: (PROMISE, "`run_async` of the `_effect` form")
            for name in (
                "decodeUnknownPromise",
                "decodePromise",
                "encodeUnknownPromise",
                "encodePromise",
            )
        },
        **{name: (INTERNAL, "not public") for name in ("_is", "_issue", "run", "asOption")},
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
        "GraphReviver": "pyfect.schema.representation.graph_reviver",
        "HashMapReviver": "pyfect.schema.representation.hash_map_reviver",
        "HashSetReviver": "pyfect.schema.representation.hash_set_reviver",
    },
    pythonic={
        "isStringSymbolReviver": (NO_UNDEFINED, "not ported"),
        "ChunkReviver": (COLLECTIONS, "an array needs no reviver"),
        **{
            name: (REVIVED_SCHEMAS, "not ported")
            for name in (
                "DateReviver",
                "FileReviver",
                "FormDataReviver",
                "URLSearchParamsReviver",
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
        "toDocumentDraft07WithDefinitionsPath": (
            "pyfect.json_schema.to_document_draft_07_with_definitions_path"
        ),
        "toDocumentDraft04": "pyfect.json_schema.to_document_draft_04",
        "toMultiDocumentOpenApi3_1": "pyfect.json_schema.to_multi_document_open_api_3_1",
    },
)

CLUSTER = Cluster(
    "schema",
    "Schema family",
    (SCHEMA, AST, GETTER, TRANSFORMATION, ISSUE, PARSER, REPRESENTATION, JSON_SCHEMA),
)
