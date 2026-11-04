"""Forge #1: ``TxHashMap[int, State].make(...)`` ignored the subscript.

A ``@staticmethod`` constructor with its own type parameters (``make[K2, V2]``)
infers from the arguments, whatever the class is subscripted with: values infer
as ``Literal['waiting']`` (or ``str``) and a later ``set(i, "running")`` fails.
A ``@classmethod`` using the class's parameters honours a subscript, but on the
bare class pyright gives them ``Unknown`` (``TxHashMap.make(...)`` is
``TxHashMap[Unknown, Unknown]``), and no overload can tell ``Unknown`` from a
subscript; a descriptor's ``__get__`` sees the same ``Unknown``.

Adopted: the class's type parameters default to a marker class, ``Unsubscripted``,
so the bare class is ``TxHashMap[Unsubscripted, Unsubscripted]``. The first overload
takes ``cls: type[TxHashMap[Unsubscripted, Unsubscripted]]`` and infers from the
arguments; the second takes the subscript. The cost: a bare annotation
(``m: TxHashMap``) is no longer reported as missing type arguments and gets the
marker, so using it is an error naming ``Unsubscripted``.
``tests/test_subscript_constructors.py`` finds every constructor and checks it.
"""

from typing import Any, Literal, overload, reveal_type


class Unsubscripted: ...


class Static[K, V]:
    @staticmethod
    def make[K2, V2](*entries: tuple[K2, V2]) -> "Static[K2, V2]": ...


class Method[K, V]:
    @classmethod
    def make(cls, *entries: tuple[K, V]) -> "Method[K, V]": ...


class Marked[K = Unsubscripted, V = Unsubscripted]:
    @overload
    @classmethod
    def make[K2, V2](
        cls: "type[Marked[Unsubscripted, Unsubscripted]]", *entries: tuple[K2, V2]
    ) -> "Marked[K2, V2]": ...
    @overload
    @classmethod
    def make(cls, *entries: tuple[K, V]) -> "Marked[K, V]": ...
    @classmethod
    def make(cls, *entries: tuple[Any, Any]) -> "Marked[Any, Any]": ...


type State = Literal["waiting", "running"]
reveal_type(Static[int, State].make((1, "waiting")))  # Static[int, str]: subscript ignored
reveal_type(Method[int, State].make((1, "waiting")))  # Method[int, State]
reveal_type(Method.make((1, "waiting")))  # Method[Unknown, Unknown]
reveal_type(Marked[int, State].make((1, "waiting")))  # Marked[int, State]
reveal_type(Marked.make((1, "waiting")))  # Marked[int, str]


def bare(m: Marked) -> None:
    reveal_type(m)  # Marked[Unsubscripted, Unsubscripted]
