"""``Some[A] | None``: an optional value that stays unambiguous when ``A``
itself admits ``None``.

pyfect uses plain ``X | None`` wherever ``X`` can't be ``None``. ``Option``
is for the places where it can: ``Some(None)`` is a present ``None``, and
``None`` is absence. Take one apart with pattern matching::

    match found:
        case Some(value):
            ...
        case None:
            ...

The functions here are Effect's ``Option`` module, data-first
(``option.map(o, f)``): ``None`` has no methods.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Never, TypeIs, cast, overload

from pyfect._some import Option, Some
from pyfect.errors import NoSuchElementException
from pyfect.result import Err, Ok, Result

Some.__module__ = __name__

void: Option[None] = Some(None)
"""``Some(None)``: present, with nothing to say."""


def is_some[A](option: Option[A]) -> TypeIs[Some[A]]:
    return option is not None


def is_none[A](option: Option[A]) -> TypeIs[None]:
    return option is None


def from_optional[A](value: A | None) -> Option[A]:
    """``None`` stays absent; anything else is present."""
    return None if value is None else Some(value)


def from_iterable[A](items: Iterable[A]) -> Option[A]:
    """The first item, if there is one."""
    return next((Some(x) for x in items), None)


def get_success[A](result: Result[A, object]) -> Option[A]:
    """An ``Ok``'s value; ``None`` for an ``Err``."""
    return Some(result.value) if isinstance(result, Ok) else None


def get_failure[E](result: Result[object, E]) -> Option[E]:
    """An ``Err``'s error; ``None`` for an ``Ok``."""
    return Some(result.error) if isinstance(result, Err) else None


def first_some_of[A](options: Iterable[Option[A]]) -> Option[A]:
    """The first present option, reading no further."""
    return next((o for o in options if o is not None), None)


def match[A, B, C](
    option: Option[A], *, on_none: Callable[[], B], on_some: Callable[[A], C]
) -> B | C:
    return on_none() if option is None else on_some(option.value)


def to_refinement[A, B](f: Callable[[A], Option[B]]) -> Callable[[A], bool]:
    """A predicate that holds where ``f`` gives an option."""
    return lambda a: f(a) is not None


def map[A, B](option: Option[A], f: Callable[[A], B]) -> Option[B]:
    return None if option is None else Some(f(option.value))


def as_[B](option: Option[object], value: B) -> Option[B]:
    return None if option is None else Some(value)


def as_void(option: Option[object]) -> Option[None]:
    return None if option is None else void


def flat_map[A, B = Never](option: Option[A], f: Callable[[A], Option[B]]) -> Option[B]:
    return None if option is None else f(option.value)


@overload
def and_then[A, B](option: Option[A], that: Callable[[A], Option[B]]) -> Option[B]: ...
@overload
def and_then[A, B](option: Option[A], that: Callable[[A], B]) -> Option[B]: ...
@overload
def and_then[B](option: Option[object], that: Option[B]) -> Option[B]: ...
@overload
def and_then[B](option: Option[object], that: B) -> Option[B]: ...
def and_then(option: Option[Any], that: Any) -> Any:
    """After a present ``option``: ``that(value)`` for a function, ``that``
    otherwise; what is not already an ``Option`` becomes ``Some``."""
    if option is None:
        return None
    result: object = that(option.value) if callable(that) else that
    if result is None or isinstance(result, Some):
        return cast("Option[Any]", result)
    return Some(result)


def flat_map_optional[A, B](option: Option[A], f: Callable[[A], B | None]) -> Option[B]:
    """``f`` may return ``None`` for absence (Effect's ``flatMapNullishOr``)."""
    return None if option is None else from_optional(f(option.value))


def flatten[A](option: Option[Option[A]]) -> Option[A]:
    return None if option is None else option.value


def tap[A](option: Option[A], f: Callable[[A], Option[object]]) -> Option[A]:
    """``option`` if ``f`` of its value is present."""
    return None if option is None or f(option.value) is None else option


def zip_left[A](option: Option[A], that: Option[object]) -> Option[A]:
    return None if that is None else option


def zip_right[B](option: Option[object], that: Option[B]) -> Option[B]:
    return None if option is None else that


def zip_with[A, B, C](option: Option[A], that: Option[B], f: Callable[[A, B], C]) -> Option[C]:
    if option is None or that is None:
        return None
    return Some(f(option.value, that.value))


def product[A, B](option: Option[A], that: Option[B]) -> Option[tuple[A, B]]:
    return zip_with(option, that, lambda a, b: (a, b))


def product_many[A](option: Option[A], options: Iterable[Option[A]]) -> Option[tuple[A, ...]]:
    """Every value, ``option``'s first, if all are present."""
    if option is None:
        return None
    rest = all(*options)
    return None if rest is None else Some((option.value, *rest.value))


@overload
def all() -> Option[tuple[()]]: ...
@overload
def all[A1](o1: Option[A1], /) -> Option[tuple[A1]]: ...
@overload
def all[A1, A2](o1: Option[A1], o2: Option[A2], /) -> Option[tuple[A1, A2]]: ...
@overload
def all[A1, A2, A3](
    o1: Option[A1], o2: Option[A2], o3: Option[A3], /
) -> Option[tuple[A1, A2, A3]]: ...
@overload
def all[A1, A2, A3, A4](
    o1: Option[A1], o2: Option[A2], o3: Option[A3], o4: Option[A4], /
) -> Option[tuple[A1, A2, A3, A4]]: ...
@overload
def all[A](*options: Option[A]) -> Option[tuple[A, ...]]: ...
def all(*options: Option[Any]) -> Option[tuple[Any, ...]]:
    """The values in order, if every option is present."""
    values: list[Any] = []
    for o in options:
        if o is None:
            return None
        values.append(o.value)
    return Some(tuple(values))


def all_dict[K, A](options: Mapping[K, Option[A]]) -> Option[dict[K, A]]:
    """The values under their keys, if every option is present."""
    values: dict[K, A] = {}
    for key, o in options.items():
        if o is None:
            return None
        values[key] = o.value
    return Some(values)


def lift2[A, B, C](f: Callable[[A, B], C]) -> Callable[[Option[A], Option[B]], Option[C]]:
    return lambda option, that: zip_with(option, that, f)


def compose_k[A, B, C](
    f: Callable[[A], Option[B]], g: Callable[[B], Option[C]]
) -> Callable[[A], Option[C]]:
    return lambda a: flat_map(f(a), g)


def reduce_compact[A, B](options: Iterable[Option[A]], initial: B, f: Callable[[B, A], B]) -> B:
    """Fold the present values, skipping absent ones."""
    out = initial
    for o in options:
        if o is not None:
            out = f(out, o.value)
    return out


def to_list[A](option: Option[A]) -> list[A]:
    return [] if option is None else [option.value]


def partition_map[A, B = Never, C = Never](
    option: Option[A], f: Callable[[A], Result[C, B]]
) -> tuple[Option[C], Option[B]]:
    """``(passes, fails)``: an ``Ok`` of ``f`` goes left, an ``Err`` right."""
    if option is None:
        return None, None
    match f(option.value):
        case Ok(value):
            return Some(value), None
        case Err(error):
            return None, Some(error)


def filter_map[A, B](option: Option[A], f: Callable[[A], Result[B, object]]) -> Option[B]:
    """Keep what a filter passes (``Ok``), as its output."""
    return None if option is None else get_success(f(option.value))


@overload
def filter[A, B](option: Option[A], predicate: Callable[[A], TypeIs[B]]) -> Option[B]: ...
@overload
def filter[A](option: Option[A], predicate: Callable[[A], bool]) -> Option[A]: ...
def filter(option: Option[Any], predicate: Callable[[Any], bool]) -> Option[Any]:
    return option if option is not None and predicate(option.value) else None


@overload
def lift_predicate[A, B](value: A, predicate: Callable[[A], TypeIs[B]]) -> Option[B]: ...
@overload
def lift_predicate[A](value: A, predicate: Callable[[A], bool]) -> Option[A]: ...
def lift_predicate(value: Any, predicate: Callable[[Any], bool]) -> Option[Any]:
    """``Some(value)`` if the predicate holds."""
    return Some(value) if predicate(value) else None


def lift_optional[**P, B](f: Callable[P, B | None]) -> Callable[P, Option[B]]:
    """``f`` with ``None`` results read as absence (Effect's ``liftNullishOr``)."""
    return lambda *args, **kwargs: from_optional(f(*args, **kwargs))


def lift_throwable[**P, B](f: Callable[P, B]) -> Callable[P, Option[B]]:
    """``f`` with a raised ``Exception`` read as absence."""

    def lifted(*args: P.args, **kwargs: P.kwargs) -> Option[B]:
        try:
            return Some(f(*args, **kwargs))
        except Exception:
            return None

    return lifted


def contains_with[A](equivalence: Callable[[A, A], bool]) -> Callable[[Option[A], A], bool]:
    """``(option, a)``: whether ``option`` holds a value equivalent to ``a``."""
    return lambda option, a: option is not None and equivalence(option.value, a)


def contains[A](option: Option[A], value: A) -> bool:
    return option is not None and option.value == value


def exists[A](option: Option[A], predicate: Callable[[A], bool]) -> bool:
    return option is not None and predicate(option.value)


def get_or_else[A, B](option: Option[A], f: Callable[[], B]) -> A | B:
    return f() if option is None else option.value


def get_or_none[A](option: Option[A]) -> A | None:
    """Back to ``A | None``, losing the distinction ``Option`` keeps."""
    return None if option is None else option.value


def get_or_raise[A](option: Option[A]) -> A:
    """The value, or raise ``NoSuchElementException``."""
    if option is None:
        raise NoSuchElementException("get_or_raise called on None")
    return option.value


def get_or_raise_with[A](option: Option[A], on_none: Callable[[], BaseException]) -> A:
    """The value, or raise ``on_none()``."""
    if option is None:
        raise on_none()
    return option.value


def or_else[A, B](option: Option[A], that: Callable[[], Option[B]]) -> Option[A | B]:
    return that() if option is None else option


def or_else_some[A, B](option: Option[A], f: Callable[[], B]) -> Option[A | B]:
    return Some(f()) if option is None else option


def or_else_result[A, B](option: Option[A], that: Callable[[], Option[B]]) -> Option[Result[B, A]]:
    """``option``'s value as an ``Err``, else ``that()``'s as an ``Ok``."""
    if option is not None:
        return Some(Err(option.value))
    return map(that(), Ok)


__all__ = [
    "Option",
    "Some",
    "all",
    "all_dict",
    "and_then",
    "as_",
    "as_void",
    "compose_k",
    "contains",
    "contains_with",
    "exists",
    "filter",
    "filter_map",
    "first_some_of",
    "flat_map",
    "flat_map_optional",
    "flatten",
    "from_iterable",
    "from_optional",
    "get_failure",
    "get_or_else",
    "get_or_none",
    "get_or_raise",
    "get_or_raise_with",
    "get_success",
    "is_none",
    "is_some",
    "lift2",
    "lift_optional",
    "lift_predicate",
    "lift_throwable",
    "map",
    "match",
    "or_else",
    "or_else_result",
    "or_else_some",
    "partition_map",
    "product",
    "product_many",
    "reduce_compact",
    "tap",
    "to_list",
    "to_refinement",
    "void",
    "zip_left",
    "zip_right",
    "zip_with",
]
