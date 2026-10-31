"""A tag is its class. ``R`` holds tag classes, and pyright counts a subclass as
its parent, so a subclass of a tag would type-check as provided by the parent
while the runtime looks it up by its own class (QA types 2). Subclassing a tag
is therefore an error unless the parent is declared a base (``base=True``),
and a base itself is never read or provided."""

from typing import Protocol

import pytest

import pyfect as fx
from pyfect import layer


class Database(Protocol):
    def query(self, sql: str) -> fx.Effect[list[str]]: ...


class Fake:
    def query(self, sql: str) -> fx.Effect[list[str]]:
        return fx.succeed([sql])


class Db(fx.Tag[Database]): ...


def test_subclassing_a_tag_is_an_error_naming_both_tags():
    with pytest.raises(TypeError, match="ReplicaDb subclasses the tag Db"):

        class ReplicaDb(Db): ...  # pyright: ignore[reportUnusedClass]


def test_subclassing_a_reference_is_an_error():
    class Level(fx.Reference[int]):
        @classmethod
        def default(cls) -> int:
            return 1

    with pytest.raises(TypeError, match=r"Other subclasses the tag .*Level"):

        class Other(Level):  # pyright: ignore[reportUnusedClass]
            @classmethod
            def default(cls) -> int:
                return 2


class Family[A](fx.Tag[A], base=True): ...


class First(Family[int]): ...


class Second(Family[int]): ...


def test_a_base_family_gives_each_subclass_its_own_service():
    both = fx.all(First(), Second()).pipe(
        fx.provide(layer.merge(layer.succeed(First, 1), layer.succeed(Second, 2)))
    )
    assert fx.run_sync(both) == (1, 2)


def test_a_base_is_neither_read_nor_provided():
    with pytest.raises(TypeError, match="Family is a base class"):
        Family()
    with pytest.raises(TypeError, match="Family is a base class"):
        layer.succeed(Family, 1)
    with pytest.raises(TypeError, match="Family is a base class"):
        fx.Context.make(Family, 1)
