"""Getters (Effect's ``SchemaGetter``): one direction of a
transformation. A ``Getter[T, E, R]`` turns a value of ``E``, or a missing
one, into a value of ``T`` or none, maybe needing services ``R``::

    from pyfect.schema import getter as G

    G.transform(int)                 # a present value through a function
    G.with_default(Success(0))       # a missing value replaced
    G.number().compose(G.transform(abs))

A transformation (``pyfect.schema.transformation``) pairs a decoding
getter with an encoding one. ``run(getter, Some(value), {})`` runs one.
"""

from pyfect.schema.getter._binary import (
    decode_base64,
    decode_base64_string,
    decode_base64_url,
    decode_base64_url_string,
    decode_hex,
    decode_hex_string,
    encode_base64,
    encode_base64_url,
    encode_hex,
)
from pyfect.schema.getter._coerce import (
    big_int,
    boolean,
    date_time_utc_from_input,
    number,
    parse_json,
    string,
    stringify_json,
)
from pyfect.schema.getter._getter import (
    Getter,
    Outcome,
    Passthrough,
    Tag,
    Transform,
    TransformEffect,
    TransformOptional,
    TransformOptionalEffect,
    run,
)
from pyfect.schema.getter._json_options import JsonReplacer, JsonReviver
from pyfect.schema.getter._make import (
    CheckOutput,
    check_effect,
    fail,
    forbidden,
    forbidden_encoding,
    omit,
    passthrough,
    passthrough_subtype,
    passthrough_supertype,
    required,
    succeed,
    transform,
    transform_effect,
    transform_optional,
    transform_optional_effect,
    with_default,
)
from pyfect.schema.getter._text import (
    camel_to_snake,
    capitalize,
    decode_uri_component,
    encode_uri_component,
    join_key_value,
    snake_to_camel,
    split,
    split_key_value,
    to_lower_case,
    to_upper_case,
    trim,
    uncapitalize,
)
from pyfect.schema.getter._tree_record import collect_bracket_path_entries, make_tree_record

__all__ = [
    "CheckOutput",
    "Getter",
    "JsonReplacer",
    "JsonReviver",
    "Outcome",
    "Passthrough",
    "Tag",
    "Transform",
    "TransformEffect",
    "TransformOptional",
    "TransformOptionalEffect",
    "big_int",
    "boolean",
    "camel_to_snake",
    "capitalize",
    "check_effect",
    "collect_bracket_path_entries",
    "date_time_utc_from_input",
    "decode_base64",
    "decode_base64_string",
    "decode_base64_url",
    "decode_base64_url_string",
    "decode_hex",
    "decode_hex_string",
    "decode_uri_component",
    "encode_base64",
    "encode_base64_url",
    "encode_hex",
    "encode_uri_component",
    "fail",
    "forbidden",
    "forbidden_encoding",
    "join_key_value",
    "make_tree_record",
    "number",
    "omit",
    "parse_json",
    "passthrough",
    "passthrough_subtype",
    "passthrough_supertype",
    "required",
    "run",
    "snake_to_camel",
    "split",
    "split_key_value",
    "string",
    "stringify_json",
    "succeed",
    "to_lower_case",
    "to_upper_case",
    "transform",
    "transform_effect",
    "transform_optional",
    "transform_optional_effect",
    "trim",
    "uncapitalize",
    "with_default",
]
