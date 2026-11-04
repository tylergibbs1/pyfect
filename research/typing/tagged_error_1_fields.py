"""Can a plain annotated subclass of ``fx.TaggedError`` get a typed field
``__init__`` while ``Boom("msg")``-style subclasses keep ``Exception``'s?

No. ``dataclass_transform`` on the base makes every subclass a dataclass to
pyright, and pyright synthesizes the ``__init__`` from the fields even when
there are none and the base writes ``__init__(*args)``: ``Plain("msg")`` is
"Expected 0 positional arguments". There is no ``init_default`` to turn the
synthesis off by default (only ``init=False`` per class). Applying ``@dataclass``
at runtime from ``__init_subclass__`` also re-runs it on explicitly decorated
classes, whose ``default_factory`` fields lose their defaults.

Without the transform, ``Fielded2(task="a")`` is a pyright error, but
``Fielded2("a")`` checks and builds an error whose ``task`` is missing.
Adopted (forge #4): constructing a ``TaggedError`` with annotated fields that no
``@dataclass`` or hand-written ``__init__`` sets raises ``TypeError`` naming the
decorator (``errors._require_dataclass_fields``, checked once per class).
"""

from dataclasses import dataclass
from typing import dataclass_transform


@dataclass_transform()
class Base(Exception):
    def __init__(self, *args: object) -> None: ...


class Plain(Base): ...


class Fielded(Base):
    task: str


Plain("msg")  # pyright: ignore[reportCallIssue]  (the rejected design)
Fielded(task="a")


class Base2(Exception): ...


class Fielded2(Base2):
    task: str


Fielded2("a")  # checks; the runtime guard catches it
Fielded2(task="a")  # pyright: ignore[reportCallIssue]


@dataclass
class Explicit(Base):
    task: str


Explicit(task="a")
