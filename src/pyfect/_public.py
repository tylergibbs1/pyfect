"""Public names for classes defined in private modules."""

import itertools
from collections.abc import Mapping, Sequence
from typing import cast


def public_home(module: str) -> str:
    """``module`` without its private part: ``pyfect.config._error`` is at
    home in ``pyfect.config``, ``pyfect._root`` in ``pyfect``."""
    return ".".join(itertools.takewhile(lambda part: not part.startswith("_"), module.split(".")))


def is_private(module: str) -> bool:
    return any(part.startswith("_") for part in module.split("."))


def publish(namespace: Mapping[str, object]) -> None:
    """Give each exception this public module exports from a private module
    under it this module's name as ``__module__``, so tracebacks and reprs
    show ``pyfect.config.ConfigError`` rather than its private file. The
    first public module to export it names it (a package's ``__init__``
    runs after its submodules'). Call it after ``__all__`` as
    ``publish(globals())``; ``tests/test_public_names.py`` checks."""
    module = namespace["__name__"]
    exported = cast("Sequence[str]", namespace.get("__all__", ()))
    assert isinstance(module, str)
    for name in exported:
        value = namespace.get(name)
        if (
            isinstance(value, type)
            and issubclass(value, BaseException)
            and is_private(value.__module__)
            and (module + ".").startswith(public_home(value.__module__) + ".")
        ):
            value.__module__ = module
