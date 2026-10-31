"""Question: can ``catch_tag(Parent)`` remove from ``E`` exactly the errors it
catches at run time (every subclass of ``Parent``), and can it tell a class
written out from a ``type[X]`` variable that may hold a subclass?

Q1. ``Effect[A, EC | ER]`` with ``EC = Parent`` against ``E = A | B | C``,
    where ``A`` and ``B`` subclass ``Parent``: what is ``ER``?
Q2. ``catch_tag(kind)`` with ``kind: type[Parent]``: does its type differ from
    ``catch_tag(Parent)``'s?

Run: ``uv run pyright -p research/typing research/typing/catch_1_subclasses.py``.

Answers:

Q1. Pyright keeps one of the subclasses in ``ER`` (which one follows its
    ordering), so with a single subclass mixed in nothing is removed. Only when every error is a
    subclass does the exact-match overload give ``Never``. So ``catch_tag``
    with a parent class is sound but leaves subclasses in ``E``; name them
    (``catch_tag((A, B), ...)``) to remove them all.
Q2. No: a class expression and a ``type[Parent]`` variable have the same
    type, and ``type[]`` is covariant, so pyright removes ``Parent`` while
    the variable may hold a subclass that catches less. No signature can
    reject the variable and keep the class.
"""

from typing import Generic, TypeVar, assert_type

E_co = TypeVar("E_co", covariant=True)


class Eff(Generic[E_co]): ...


class Parent: ...


class A(Parent): ...


class B(Parent): ...


class C: ...


def catch[EC, ER](tag: type[EC], eff: Eff[EC | ER]) -> Eff[ER]: ...


def q1(mixed: Eff[A | B | C], one: Eff[B | C]) -> None:
    assert_type(catch(Parent, mixed), Eff[A | C])  # B removed, A kept
    assert_type(catch(Parent, one), Eff[B | C])  # nothing removed


def q2(kind: type[Parent]) -> None:
    assert_type(kind, type[Parent])
    assert_type(Parent, type[Parent])
