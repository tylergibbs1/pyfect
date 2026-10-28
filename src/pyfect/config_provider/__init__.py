"""Configuration sources (Effect's ``ConfigProvider``).

A ``ConfigProvider`` looks a path up and finds a ``Node``: a ``Value``
(a string), a ``Record`` (child keys) or an ``Array`` (a length), or
``None`` when nothing is there::

    provider = config_provider.from_env(env={"APP_PORT": "3000"})
    provider.load(("APP", "PORT"))  # Effect[Node | None, SourceError]: Value("3000")

Sources: ``from_env`` (``os.environ`` by default), ``from_env_record``,
``from_unknown`` (nested dicts and lists), ``from_dot_env_contents`` /
``from_dot_env`` (``.env`` files), ``from_dir`` (a file per key) and
``make`` (any lookup function). Combinators are methods: ``or_else``,
``map_input``, ``nested``, ``constant_case``. ``CurrentConfigProvider`` is
the provider configuration is read from (``from_env()`` unless a ``layer``
or ``layer_add`` installs another)."""

from pyfect.config_provider._dir import from_dir
from pyfect.config_provider._dotenv import from_dot_env, from_dot_env_contents
from pyfect.config_provider._env import from_env, from_env_record
from pyfect.config_provider._layers import layer, layer_add
from pyfect.config_provider._node import (
    Array,
    Keys,
    Node,
    Path,
    PathInput,
    Record,
    Segment,
    SourceError,
    Value,
)
from pyfect.config_provider._provider import ConfigProvider, CurrentConfigProvider, make
from pyfect.config_provider._unknown import from_unknown

__all__ = [
    "Array",
    "ConfigProvider",
    "CurrentConfigProvider",
    "Keys",
    "Node",
    "Path",
    "PathInput",
    "Record",
    "Segment",
    "SourceError",
    "Value",
    "from_dir",
    "from_dot_env",
    "from_dot_env_contents",
    "from_env",
    "from_env_record",
    "from_unknown",
    "layer",
    "layer_add",
    "make",
]
