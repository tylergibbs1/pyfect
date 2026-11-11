"""Typed configuration (Effect's ``Config``).

A ``Config[A]`` says which keys to read from the ``CurrentConfigProvider``
and how to decode them. It is an effect, failing with ``ConfigError``::

    @fx.gen
    def main():
        port = yield from config.port("PORT").with_default(8080)
        ...

Each read resolves in two channels: data that is not there is *absent*
(``with_default`` and ``option`` recover it), data that is there but
invalid *fails* (only ``or_else`` recovers it). Constructors read one string
(``string``, ``integer``, ``port``, ``boolean``, ``duration``, ``literal``,
``url``, ``log_level``, ``byte_size``, ``redacted``, ...) or a container
(``list_of``, ``dict_of``); ``all`` / ``all_dict`` group configs, ``gen``
builds one from a generator, and the methods ``map``, ``flat_map``,
``map_effect``, ``or_else``, ``with_default`` and ``nested`` transform one.
``schema(codec, path)`` reads any shape a schema describes (Effect's
``Config.schema``).
"""

from pyfect._public import publish
from pyfect.config._all import all, all_dict
from pyfect.config._collections import dict_of, list_of
from pyfect.config._config import Config, gen, option, unwrap
from pyfect.config._config import fail_config as fail
from pyfect.config._config import succeed_config as succeed
from pyfect.config._constructors import (
    DurationConfig,
    boolean,
    byte_size,
    date_time,
    duration,
    finite,
    integer,
    literal,
    log_level,
    non_empty_string,
    number,
    port,
    redacted,
    string,
    url,
)
from pyfect.config._error import ConfigError
from pyfect.config._schema import schema
from pyfect.schema import SchemaError
from pyfect.schema.issue import (
    Composite,
    Forbidden,
    InvalidType,
    InvalidValue,
    Issue,
    Pointer,
)

__all__ = [
    "Composite",
    "Config",
    "ConfigError",
    "DurationConfig",
    "Forbidden",
    "InvalidType",
    "InvalidValue",
    "Issue",
    "Pointer",
    "SchemaError",
    "all",
    "all_dict",
    "boolean",
    "byte_size",
    "date_time",
    "dict_of",
    "duration",
    "fail",
    "finite",
    "gen",
    "integer",
    "list_of",
    "literal",
    "log_level",
    "non_empty_string",
    "number",
    "option",
    "port",
    "redacted",
    "schema",
    "string",
    "succeed",
    "unwrap",
    "url",
]

publish(globals())
