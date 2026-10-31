"""How should Effect's ``Atom`` be spelled in Python so pyright infers what
Effect's TypeScript infers?

Run with ``uv run pyright -p research/typing research/typing/atom_1_spelling.py``.

Findings (pyright 1.1.414):

A1. A derived atom's getter is an ``AtomContext`` object with a generic
    ``__call__[A](atom: Atom[A]) -> A``. ``make(lambda get: get(a) + 1)``
    infers ``Atom[int]``: pyright gives the lambda its parameter type from
    each overload's ``Callable[[AtomContext], ...]`` in turn.
A2. ``make``'s overloads, in order: an effect, a stream, a function
    returning an effect, a function returning a stream, any function, then
    a plain value (``Writable[A, A]``). A function returning ``int`` skips
    the effect overloads and lands on ``Atom[int]``.
A3. Requirements: the effect overloads take ``Effect[A, E, Scope |
    AtomRegistry]``. ``Effect`` is covariant in ``R``, so an effect needing
    nothing or only those matches and one needing another service does not.
    It would then fall through to the plain-value overload and become a
    ``Writable[Effect[...]]`` holding the effect, silently. A
    ``@deprecated`` overload placed before the value overload, taking any
    ``Effect`` / ``Stream``, makes that a strict-mode error
    (``reportDeprecated`` is an error under ``strict``) that names the fix.
A4. A runtime atom (``AtomRuntime[R, ER]``) takes its services from the
    class: ``runtime.atom(eff)`` checks ``eff`` against ``Scope | R |
    AtomRegistry | Reactivity`` and adds ``ER`` to the error, with the
    method's own ``A`` / ``E``. One effect overload per form is enough.
A5. ``Writable[R, W]``: ``R`` covariant, ``W`` contravariant, so
    ``registry.set(atom, value)`` checks ``value`` against ``W`` and a
    ``Writable[int, int]`` is an ``Atom[int]``.
A6. Combinators that keep a writable writable (``map``, ``transform``,
    ``with_fallback``) are methods overridden on ``Writable`` with the
    narrower return type, which pyright accepts as a compatible override.
    ``keep_alive`` and friends return ``Self``.
A7. ``fn(f)`` with ``f: Callable[[Arg, FnContext], Effect[A, E, ...]]``
    solves ``AtomResultFn[Arg, A, E]`` from a ``def`` with an annotated
    ``Arg``; a lambda's ``Arg`` is unknown (strict flags it), so the
    tests use ``def`` (Effect's ``Atom.fn<Arg>()`` curried form only
    exists to annotate a lambda, which Python cannot).
A8. A family is ``Callable[[Arg], T]`` keyed by ``Equal`` on ``Arg``
    (``family(f)`` returns ``f``'s type).
A9. Effect-returning operations (``get``, ``set``, ``get_result``) need
    ``AtomRegistry`` in ``R``; ``provide_service(AtomRegistry, registry)``
    removes it.
A10. ``optimistic_fn`` is data-first: with the optimistic atom first, the
    reducer lambda's ``current`` is typed from it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Never, Self, TypeVar, assert_type, overload

from typing_extensions import deprecated

from pyfect import Effect, Tag, succeed
from pyfect.scope import Scope
from pyfect.stream import Stream

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
W_contra = TypeVar("W_contra", contravariant=True)


class AsyncResult(Generic[A_co, E_co]): ...


class AtomRegistryService: ...


class AtomRegistry(Tag[AtomRegistryService], key="probe/AtomRegistry"): ...


class Reactivity(Tag[object], key="probe/Reactivity"): ...


class Other(Tag[int], key="probe/Other"): ...


class Atom(Generic[A_co]):
    def keep_alive(self) -> Self: ...
    def map[B](self, f: Callable[[A_co], B]) -> Atom[B]: ...


class Writable(Atom[A_co], Generic[A_co, W_contra]):
    def map[B](self, f: Callable[[A_co], B]) -> Writable[B, W_contra]: ...


class AtomContext:
    def __call__[A](self, atom: Atom[A], /) -> A: ...
    def get[A](self, atom: Atom[A], /) -> A: ...


class FnContext(AtomContext): ...


class AtomResultFn[Arg, A, E](Writable[AsyncResult[A, E], Arg]): ...


@overload
def make[A, E = Never](  # pyright: ignore[reportOverlappingOverload]
    effect: Effect[A, E, Scope | AtomRegistry], /
) -> Atom[AsyncResult[A, E]]: ...
@overload
def make[A, E = Never](
    stream: Stream[A, E, AtomRegistry], /
) -> Atom[AsyncResult[A, E | LookupError]]: ...
@overload
def make[A, E = Never](
    create: Callable[[AtomContext], Effect[A, E, Scope | AtomRegistry]],
    /,
) -> Atom[AsyncResult[A, E]]: ...
@overload
def make[A, E = Never](
    create: Callable[[AtomContext], Stream[A, E, AtomRegistry]],
    /,
) -> Atom[AsyncResult[A, E | LookupError]]: ...
@overload
def make[A](create: Callable[[AtomContext], A], /) -> Atom[A]: ...
@overload
@deprecated("needs services an atom cannot provide: build it with a runtime atom")
def make(effect: Effect[Any, Any, Any] | Stream[Any, Any, Any], /) -> Never: ...
@overload
def make[A](initial: A, /) -> Writable[A, A]: ...
def make(arg: Any, /) -> Any: ...


def fn[Arg, A, E = Never](
    f: Callable[[Arg, FnContext], Effect[A, E, Scope | AtomRegistry]],
    /,
) -> AtomResultFn[Arg, A, E]: ...


def family[Arg, T](f: Callable[[Arg], T]) -> Callable[[Arg], T]: ...


def get[A](atom: Atom[A]) -> Effect[A, Never, AtomRegistry]: ...


def set_[R, W](registry: AtomRegistryService, atom: Writable[R, W], value: W) -> None: ...


class AtomRuntime(Atom[AsyncResult[object, Any]], Generic[A_co, E_co]):
    def atom[A, E = Never](
        self, effect: Effect[A, E, Scope | A_co | AtomRegistry | Reactivity]
    ) -> Atom[AsyncResult[A, E | E_co]]: ...


def optimistic_fn[A, W, OW, XA, XE](
    self: Writable[A, Atom[AsyncResult[W, object]]],
    *,
    reducer: Callable[[A, OW], W],
    fn: AtomResultFn[OW, XA, XE],
) -> AtomResultFn[OW, XA, XE]: ...


# A1 / A2
counter = make(0)
assert_type(counter, Writable[int, int])
double = make(lambda get: get(counter) * 2)
assert_type(double, Atom[int])
via_method = make(lambda get: get.get(counter) + 1)
assert_type(via_method, Atom[int])

# A3
eff_atom = make(succeed(1))
assert_type(eff_atom, Atom[AsyncResult[int, Never]])
from_fn = make(lambda get: succeed(get(counter)))
assert_type(from_fn, Atom[AsyncResult[int, Never]])


def needs_registry_eff() -> Effect[int, str, AtomRegistry]: ...


def needs_other_eff() -> Effect[int, Never, Other]: ...


needs_registry = needs_registry_eff()
assert_type(make(needs_registry), Atom[AsyncResult[int, str]])
needs_other = needs_other_eff()
make(needs_other)  # pyright: ignore[reportDeprecated]

# A4
runtime: AtomRuntime[Other, ValueError] = AtomRuntime()
assert_type(runtime.atom(needs_other), Atom[AsyncResult[int, ValueError]])
assert_type(runtime.atom(needs_registry), Atom[AsyncResult[int, str | ValueError]])

# A5
registry = AtomRegistryService()
set_(registry, counter, 2)
set_(registry, counter, "x")  # pyright: ignore[reportArgumentType]
as_atom: Atom[int] = counter

# A6
assert_type(counter.map(str), Writable[str, int])
assert_type(double.map(str), Atom[str])
assert_type(counter.keep_alive(), Writable[int, int])


# A7
def inc(n: int, get: FnContext) -> Effect[int]:
    return succeed(n + get(counter))


assert_type(fn(inc), AtomResultFn[int, int, Never])

# A8
by_id = family(lambda n: make(n))  # pyright: ignore[reportUnknownVariableType, reportUnknownLambdaType]
labelled: Callable[[int], Writable[int, int]] = family(make)

# A9
assert_type(get(counter), Effect[int, Never, AtomRegistry])

# A10
optimistic: Writable[int, Atom[AsyncResult[int, object]]] = Writable()
result_fn = optimistic_fn(optimistic, reducer=lambda current, update: current + update, fn=fn(inc))
assert_type(result_fn, AtomResultFn[int, int, Never])
