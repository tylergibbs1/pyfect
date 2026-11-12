"""The optional dependencies (extras) and the error raised when one is
missing. Every module that imports an extra's library goes through
``missing_extra`` (``tests/test_install.py`` checks), so the error names the
extra and how to install it when the library is absent, and shows the real
error when the library is installed but fails to import."""

from collections.abc import Mapping
from typing import Final, Literal

type Extra = Literal[
    "otel",
    "hypothesis",
    "pydantic",
    "msgspec",
    "httpx",
    "websockets",
    "pg",
    "mysql",
    "mssql",
    "server",
    "http2",
    "intl",
    "regex",
    "redis",
    "eventlog",
    "brotli",
    "crypto",
    "watch",
]
"""The ``[project.optional-dependencies]`` of ``pyproject.toml``."""

LIBRARIES: Final[Mapping[Extra, frozenset[str]]] = {
    "otel": frozenset({"opentelemetry"}),
    "hypothesis": frozenset({"hypothesis"}),
    "pydantic": frozenset({"pydantic", "pydantic_core"}),
    "msgspec": frozenset({"msgspec"}),
    "httpx": frozenset({"httpx"}),
    "websockets": frozenset({"websockets"}),
    "pg": frozenset({"psycopg"}),
    "mysql": frozenset({"asyncmy"}),
    "mssql": frozenset({"pytds", "OpenSSL"}),
    "server": frozenset({"uvicorn", "websockets"}),
    "http2": frozenset({"hypercorn"}),
    # date_time.intl ships its own data now; the extra installs nothing.
    "intl": frozenset(),
    "regex": frozenset({"regex"}),
    "redis": frozenset({"redis"}),
    "eventlog": frozenset({"cryptography", "nacl"}),
    "brotli": frozenset({"brotlicffi"}),
    "crypto": frozenset({"cryptography", "nacl"}),
    "watch": frozenset({"watchfiles"}),
}
"""The top-level import names of each extra's libraries."""

DISTRIBUTION: Final = "pyfect-dev"
"""The distribution name (the import name is ``pyfect``; PyPI's ``pyfect``
is an unrelated project)."""


def install_command(extra: Extra | None = None) -> str:
    """The command that installs pyfect, with ``extra`` if given."""
    if extra is None:
        return f"uv add {DISTRIBUTION}"
    return f'uv add "{DISTRIBUTION}[{extra}]"'


def is_absent(error: ImportError, extra: Extra) -> bool:
    """Whether ``error`` says one of ``extra``'s libraries is not installed,
    rather than installed and failing to import (a missing system library
    such as libpq, a broken build, a missing dependency of its own)."""
    return isinstance(error, ModuleNotFoundError) and error.name in LIBRARIES[extra]


def missing_extra(feature: str, extra: Extra, error: ImportError) -> ImportError:
    """The error to raise ``from error`` when importing ``extra``'s
    libraries for ``feature`` failed: how to install the extra when a library
    is absent, and otherwise ``error``'s own message."""
    if is_absent(error, extra):
        return ImportError(f"{feature} needs the {extra!r} extra: {install_command(extra)}")
    return ImportError(
        f"{feature} could not import the {extra!r} extra's libraries, which are installed: {error}"
    )
