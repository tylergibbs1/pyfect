"""What routes and middleware leave for the server to satisfy.

These classes only appear in a layer's requirements, never at run time.
``add`` puts ``Requires[R] | Raises[E]`` there for a handler with
requirements ``R`` and errors ``E``; ``serve``, ``to_web_handler`` and
``to_http_effect`` collect them into the app's types. Python cannot split
a union, so a middleware's ``provides`` does not remove its services from
a route's ``Requires``; only what the server must supply counts."""

from __future__ import annotations


class Requires[R]:
    """A route needs the services ``R`` for each request."""

    @property
    def services(self) -> R:
        raise TypeError("Requires is a type-level marker")


class Raises[E]:
    """A route can fail with ``E``."""

    @property
    def error(self) -> E:
        raise TypeError("Raises is a type-level marker")


class GlobalRequires[R]:
    """A global middleware needs the services ``R`` for each request."""

    @property
    def services(self) -> R:
        raise TypeError("GlobalRequires is a type-level marker")


class GlobalRaises[E]:
    """A global middleware can fail with ``E``."""

    @property
    def error(self) -> E:
        raise TypeError("GlobalRaises is a type-level marker")


class Unhandled(Exception):
    """The errors a middleware passes on unhandled (Effect's
    ``Types.unhandled``). A middleware's result must keep it."""
