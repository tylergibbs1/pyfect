"""Transformations (Effect's ``SchemaTransformation``): a decoding getter
and an encoding one, which ``S.decode_to`` puts between two schemas::

    from pyfect.schema import transformation as T

    S.String.pipe(S.decode_to(S.Number, T.number_from_string))
    T.transform(decode=int, encode=str)

A ``Middleware`` instead takes the source's whole parse, failures
included (``S.middleware_decoding``, ``S.catch_decoding``).
"""

from pyfect.schema.transformation._builtins import (
    big_int_from_string,
    byte_size_from_big_int,
    byte_size_from_number,
    byte_size_from_string,
    bytes_from_base64_string,
    capitalize,
    date_time_utc_from_string,
    date_time_zoned_from_string,
    from_json_string,
    number_from_string,
    option_from_null_or,
    option_from_optional_key,
    snake_to_camel,
    split_key_value,
    string_from_base64_string,
    string_from_base64_url_string,
    string_from_hex_string,
    string_from_uri_component,
    time_zone_from_string,
    time_zone_named_from_string,
    to_lower_case,
    to_upper_case,
    trim,
    uncapitalize,
    url_from_string,
)
from pyfect.schema.transformation._transformation import (
    Middleware,
    Transformation,
    is_transformation,
    passthrough,
    passthrough_subtype,
    passthrough_supertype,
    transform,
    transform_effect,
    transform_optional,
)

__all__ = [
    "Middleware",
    "Transformation",
    "big_int_from_string",
    "byte_size_from_big_int",
    "byte_size_from_number",
    "byte_size_from_string",
    "bytes_from_base64_string",
    "capitalize",
    "date_time_utc_from_string",
    "date_time_zoned_from_string",
    "from_json_string",
    "is_transformation",
    "number_from_string",
    "option_from_null_or",
    "option_from_optional_key",
    "passthrough",
    "passthrough_subtype",
    "passthrough_supertype",
    "snake_to_camel",
    "split_key_value",
    "string_from_base64_string",
    "string_from_base64_url_string",
    "string_from_hex_string",
    "string_from_uri_component",
    "time_zone_from_string",
    "time_zone_named_from_string",
    "to_lower_case",
    "to_upper_case",
    "transform",
    "transform_effect",
    "transform_optional",
    "trim",
    "uncapitalize",
    "url_from_string",
]
