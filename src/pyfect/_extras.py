"""The optional dependencies (extras) and the error raised when one is
missing. Every module that imports an extra's library goes through
``missing_extra`` (``tests/test_install.py`` checks), so the error always
names the extra and how to install it."""

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
]
"""The ``[project.optional-dependencies]`` of ``pyproject.toml``."""

DISTRIBUTION: Final = "pyfect-dev"
"""The distribution name (the import name is ``pyfect``; PyPI's ``pyfect``
is an unrelated project)."""


def install_command(extra: Extra | None = None) -> str:
    """The command that installs pyfect, with ``extra`` if given."""
    if extra is None:
        return f"uv add {DISTRIBUTION}"
    return f'uv add "{DISTRIBUTION}[{extra}]"'


def missing_extra(feature: str, extra: Extra) -> ImportError:
    """The error for ``feature`` used without ``extra`` installed; raise it
    ``from`` the original ``ImportError``."""
    return ImportError(f"{feature} needs the {extra!r} extra: {install_command(extra)}")
