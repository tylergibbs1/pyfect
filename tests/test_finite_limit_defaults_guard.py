"""Every limit reference (a ``Reference`` named ``Max...``) has a finite default.

An unbounded default lets one request from anyone spend a server's memory, disk or CPU:
multipart's ``MaxParts`` was unlimited (as in Effect) until 0.7.0, so one request within
the body limit could make tens of thousands of temporary files. A limit may default to
``None`` only when a finite limit around it already bounds it; ``BOUNDED_BY`` names that
limit.
"""

from typing import Any

from _pyfect_modules import modules

from pyfect.context import Reference

BOUNDED_BY = {
    # A file part is part of the body, which MaxBodySize bounds.
    "pyfect.http.multipart.MaxFileSize": "pyfect.http.incoming_message.MaxBodySize",
}


def _limits() -> dict[str, type[Reference[Any]]]:
    found: dict[str, type[Reference[Any]]] = {}
    for module in modules(skip_missing_extras=True):
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, Reference)
                and value.__name__.startswith("Max")
                and value.__module__ == module.__name__
            ):
                found[f"{value.__module__}.{value.__qualname__}"] = value
    return found


def test_the_walk_finds_the_body_limits() -> None:
    limits = _limits()
    assert {
        "pyfect.http.multipart.MaxParts",
        "pyfect.http.multipart.MaxPersistedFiles",
        "pyfect.http.multipart.MaxPersistedSize",
        "pyfect.http.incoming_message.MaxBodySize",
    } <= limits.keys()


def test_every_limit_reference_has_a_finite_default() -> None:
    limits = _limits()
    unbounded = sorted(
        name
        for name, limit in limits.items()
        if limit.default() is None
        and (name not in BOUNDED_BY or limits[BOUNDED_BY[name]].default() is None)
    )
    assert not unbounded, (
        f"give these a finite default or name the limit bounding them: {unbounded}"
    )
