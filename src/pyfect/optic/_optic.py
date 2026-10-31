"""The optic classes (Effect's ``Optional``, ``Lens``, ``Prism``, ``Iso``).

``Optional[S, A]`` focuses on an ``A`` that may be missing from an ``S``,
and writing it back may fail; a ``Lens`` always finds its focus; a
``Prism`` writes without the source; an ``Iso`` is both. Composing two
optics gives the weakest of their kinds (``Lens`` then ``Prism`` is an
``Optional``). Every operation is pure: the source is copied, never
changed.

A key's focus is typed ``Any`` (Python cannot compute the type of a key of
a ``TypedDict``); annotate the optic to name it: ``name: Lens[User, str] =
Id[User]().key("name")``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import Any, TypeIs, cast, overload

from pyfect import _json_text
from pyfect.optic import _data
from pyfect.optic._steps import (
    Kind,
    Step,
    checks_step,
    compile_get,
    compile_set,
    kind_of,
    path_step,
    same,
)
from pyfect.optic._steps import compose as compose_steps
from pyfect.result import Err, Ok, Result
from pyfect.schema import ast
from pyfect.schema.issue import InvalidValue, Issue, MissingKey, Pointer

type Traversal[T, E] = Optional[T, Sequence[E]]
"""An optic focusing on several values at once (Effect's ``Traversal``):
an ``Optional`` whose focus is a sequence."""


class Optional[S, A]:
    """A focus that may be missing, and a write that may fail (Effect's
    ``Optional``). ``replace`` and ``modify`` give the source back unchanged
    when they fail; ``get_result`` and ``replace_result`` say why."""

    def __init__(
        self,
        steps: tuple[Step, ...],
        get_result: Callable[[S], Result[A, Issue]],
        replace_result: Callable[[A, S], Result[S, Issue]],
    ) -> None:
        self._steps = steps
        self._get_result = get_result
        self._replace_result = replace_result

    def get_result(self, s: S, /) -> Result[A, Issue]:
        """The focus of ``s``, or the issue saying why there is none."""
        return self._get_result(s)

    def replace_result(self, a: A, s: S, /) -> Result[S, Issue]:
        """``s`` with ``a`` in place of its focus, or why it cannot be."""
        return self._replace_result(a, s)

    def replace(self, a: A, s: S, /) -> S:
        """``s`` with ``a`` in place of its focus; ``s`` itself on failure."""
        out = self.replace_result(a, s)
        return out.value if isinstance(out, Ok) else s

    def modify(self, f: Callable[[A], A], /) -> Callable[[S], S]:
        """A function updating the focus with ``f``; it gives the source back
        when there is no focus or it cannot be written."""

        def modify(s: S) -> S:
            got = self.get_result(s)
            if isinstance(got, Err):
                return s
            return self.replace(f(got.value), s)

        return modify

    @overload
    def compose[B](self: Iso[S, A], that: Iso[A, B], /) -> Iso[S, B]: ...
    @overload
    def compose[B](self: Lens[S, A], that: Lens[A, B], /) -> Lens[S, B]: ...
    @overload
    def compose[B](self: Prism[S, A], that: Prism[A, B], /) -> Prism[S, B]: ...
    @overload
    def compose[B](self: Optional[S, A], that: Optional[A, B], /) -> Optional[S, B]: ...
    def compose(self, that: Optional[Any, Any], /) -> Any:
        """This optic, then ``that`` on its focus; the kind is the weaker."""
        return make(compose_steps(self._steps, that._steps))

    def _then(self, steps: tuple[Step, ...]) -> Any:
        return make(compose_steps(self._steps, steps))

    @overload
    def key(self: Lens[S, A], key: Hashable, /) -> Lens[S, Any]: ...
    @overload
    def key(self: Optional[S, A], key: Hashable, /) -> Optional[S, Any]: ...
    def key(self, key: Hashable, /) -> Any:
        """The value at ``key``: a dict key, a list or tuple index, or an
        attribute of a dataclass. A missing one reads as ``None``."""
        return self._then((path_step((key,)),))

    @overload
    def optional_key(self: Lens[S, A], key: Hashable, /) -> Lens[S, Any]: ...
    @overload
    def optional_key(self: Optional[S, A], key: Hashable, /) -> Optional[S, Any]: ...
    def optional_key(self, key: Hashable, /) -> Any:
        """The value at ``key``, ``None`` when missing; writing ``None``
        removes the key (an element is removed, later ones move down)."""

        def replace(a: object, s: object) -> object:
            return _data.remove(s, key) if a is None else _data.assign(s, key, a)

        return self._then((Step("Lens", lambda s: _data.get(s, key), replace),))

    @overload
    def check(self: Prism[S, A], *checks: ast.Check[A]) -> Prism[S, A]: ...
    @overload
    def check(self: Optional[S, A], *checks: ast.Check[A]) -> Optional[S, A]: ...
    def check(self, *checks: ast.Check[Any]) -> Any:
        """Only a focus every check accepts; the issue holds each failure."""
        first, *rest = checks
        return self._then((checks_step((first, *rest)),))

    @overload
    def refine[B](
        self: Prism[S, A], guard: Callable[[A], TypeIs[B]], /, **annotations: object
    ) -> Prism[S, B]: ...
    @overload
    def refine[B](
        self: Optional[S, A], guard: Callable[[A], TypeIs[B]], /, **annotations: object
    ) -> Optional[S, B]: ...
    def refine(self, guard: Callable[[Any], bool], /, **annotations: object) -> Any:
        """Only a focus ``guard`` accepts, narrowed to its type; the issue is
        ``Expected <expected>`` (the ``expected`` annotation)."""
        return self._then((checks_step((ast.make_filter_by_guard(guard, annotations or None),)),))

    @overload
    def tag(self: Prism[S, A], tag: ast.LiteralValue, /) -> Prism[S, A]: ...
    @overload
    def tag(self: Optional[S, A], tag: ast.LiteralValue, /) -> Optional[S, A]: ...
    def tag(self, tag: ast.LiteralValue, /) -> Any:
        """Only a focus whose ``_tag`` (a key or an attribute) is ``tag``."""
        issue: Err[Issue] = Err(InvalidValue({"expected": f"{_json_text.stringify(tag)} tag"}))

        def get(s: object) -> Result[object, Issue]:
            found = _data.get(s, "_tag") if _data.has(s, "_tag") else None
            return Ok(s) if found == tag else issue

        return self._then((Step("Prism", get, same),))

    def at(self, key: Hashable, /) -> Optional[S, Any]:
        """The value at ``key`` when ``s`` has it: a missing key is an issue
        (``MissingKey`` at ``key``), and writing needs the key there."""
        missing: Err[Issue] = Err(Pointer((key,), MissingKey()))

        def get(s: object) -> Result[object, Issue]:
            return Ok(_data.get(s, key)) if _data.has(s, key) else missing

        def replace(a: object, s: object) -> Result[object, Issue]:
            return Ok(_data.assign(s, key, a)) if _data.has(s, key) else missing

        return self._then((Step("Optional", get, replace),))

    @overload
    def pick(self: Lens[S, A], *keys: Hashable) -> Lens[S, dict[Any, Any]]: ...
    @overload
    def pick(self: Optional[S, A], *keys: Hashable) -> Optional[S, dict[Any, Any]]: ...
    def pick(self, *keys: Hashable) -> Any:
        """A dict of the ``keys`` the focus has; writing it replaces those
        keys (one left out of the replacement is deleted)."""
        return self._then((Step("Lens", _picker(keys, True), _merger(keys, True)),))

    @overload
    def omit(self: Lens[S, A], *keys: Hashable) -> Lens[S, dict[Any, Any]]: ...
    @overload
    def omit(self: Optional[S, A], *keys: Hashable) -> Optional[S, dict[Any, Any]]: ...
    def omit(self, *keys: Hashable) -> Any:
        """A dict of the focus without ``keys``; writing it replaces every
        other key."""
        return self._then((Step("Lens", _picker(keys, False), _merger(keys, False)),))

    @overload
    def not_none[B](self: Prism[S, B | None]) -> Prism[S, B]: ...
    @overload
    def not_none[B](self: Optional[S, B | None]) -> Optional[S, B]: ...
    def not_none(self) -> Any:
        """Only a focus that is not ``None`` (Effect's ``notUndefined``)."""
        guard = ast.make_filter_by_guard(_is_not_none, {"expected": "a value other than `None`"})
        return self._then((checks_step((guard,)),))

    @overload
    def for_each[E, B](
        self: Optional[S, list[E]], f: Callable[[Iso[E, E]], Optional[E, B]], /
    ) -> Optional[S, list[B]]: ...
    @overload
    def for_each[E, B](
        self: Optional[S, tuple[E, ...]], f: Callable[[Iso[E, E]], Optional[E, B]], /
    ) -> Optional[S, tuple[B, ...]]: ...
    @overload
    def for_each[E, B](
        self: Optional[S, Sequence[E]], f: Callable[[Iso[E, E]], Optional[E, B]], /
    ) -> Optional[S, Sequence[B]]: ...
    def for_each(self, f: Callable[[Any], Optional[Any, Any]], /) -> Any:
        """Each element's focus under ``f``'s optic, in order (those it finds);
        writing takes one replacement per element found, in the same
        container type as the source."""
        inner = f(Id[Any]())
        this = cast("Optional[Any, Sequence[Any]]", self)

        def get(s: object) -> Result[Sequence[Any], Issue]:
            got = this.get_result(s)
            if isinstance(got, Err):
                return got
            found = [r.value for r in map(inner.get_result, got.value) if isinstance(r, Ok)]
            return Ok(_like(got.value, found))

        def replace(bs: Sequence[Any], s: object) -> Result[object, Issue]:
            got = this.get_result(s)
            if isinstance(got, Err):
                return got
            items = got.value
            indexes = [i for i, a in enumerate(items) if isinstance(inner.get_result(a), Ok)]
            if len(bs) != len(indexes):
                message = f"each: replacement length mismatch: {len(bs)} !== {len(indexes)}"
                return Err(InvalidValue({"message": message}))
            out = list(items)
            for i, b in zip(indexes, bs, strict=True):
                replaced = inner.replace_result(b, items[i])
                if isinstance(replaced, Err):
                    return Err(Pointer((i,), replaced.error))
                out[i] = replaced.value
            return this.replace_result(_like(items, out), s)

        return make_optional(get, replace)

    @overload
    def modify_all[E](self: Optional[S, list[E]], f: Callable[[E], E], /) -> Callable[[S], S]: ...
    @overload
    def modify_all[E](
        self: Optional[S, tuple[E, ...]], f: Callable[[E], E], /
    ) -> Callable[[S], S]: ...
    @overload
    def modify_all[E](
        self: Optional[S, Sequence[E]], f: Callable[[E], E], /
    ) -> Callable[[S], S]: ...
    def modify_all(self, f: Callable[[Any], Any], /) -> Callable[[S], S]:
        """A function applying ``f`` to every focused element; it gives the
        source back when the traversal fails."""
        this = cast("Optional[S, Sequence[Any]]", self)

        def modify(s: S) -> S:
            got = this.get_result(s)
            if isinstance(got, Err):
                return s
            return this.replace(_like(got.value, [f(a) for a in got.value]), s)

        return modify

    @overload
    def get_all[E](self: Optional[S, list[E]], s: S, /) -> list[E]: ...
    @overload
    def get_all[E](self: Optional[S, tuple[E, ...]], s: S, /) -> list[E]: ...
    @overload
    def get_all[E](self: Optional[S, Sequence[E]], s: S, /) -> list[E]: ...
    def get_all(self, s: S, /) -> list[Any]:
        """Every focused element, or none when the traversal fails."""
        got = cast("Optional[S, Sequence[Any]]", self).get_result(s)
        return list(got.value) if isinstance(got, Ok) else []


class Lens[S, A](Optional[S, A]):
    """A focus that is always there (Effect's ``Lens``)."""

    def __init__(
        self, steps: tuple[Step, ...], get: Callable[[S], A], replace: Callable[[A, S], S]
    ) -> None:
        super().__init__(steps, lambda s: Ok(get(s)), lambda a, s: Ok(replace(a, s)))
        self._get = get
        self._replace = replace

    def get(self, s: S, /) -> A:
        """The focus of ``s``."""
        return self._get(s)

    def replace(self, a: A, s: S, /) -> S:
        return self._replace(a, s)

    def modify(self, f: Callable[[A], A], /) -> Callable[[S], S]:
        return lambda s: self._replace(f(self._get(s)), s)


class Prism[S, A](Optional[S, A]):
    """A focus that may be missing, written without the source (Effect's
    ``Prism``): ``set(a)`` builds a whole ``S``."""

    def __init__(
        self,
        steps: tuple[Step, ...],
        get_result: Callable[[S], Result[A, Issue]],
        set: Callable[[A], S],
    ) -> None:
        super().__init__(steps, get_result, lambda a, _: Ok(set(a)))
        self._set = set

    def set(self, a: A, /) -> S:
        """The whole ``S`` made from ``a``."""
        return self._set(a)

    def replace(self, a: A, s: S, /) -> S:
        return self._set(a)

    def modify(self, f: Callable[[A], A], /) -> Callable[[S], S]:
        def modify(s: S) -> S:
            got = self.get_result(s)
            return s if isinstance(got, Err) else self._set(f(got.value))

        return modify


class Iso[S, A](Lens[S, A], Prism[S, A]):
    """A lossless conversion both ways (Effect's ``Iso``): both a ``Lens``
    and a ``Prism``."""

    def __init__(self, steps: tuple[Step, ...], get: Callable[[S], A], set: Callable[[A], S]):
        def get_result(s: S) -> Result[A, Issue]:
            return Ok(get(s))

        def replace(a: A, _: S) -> S:
            return set(a)

        # Prism's constructor (next after Lens in the MRO) sets the rest.
        super(Lens, self).__init__(steps, get_result, set)
        self._get = get
        self._replace = replace

    def replace(self, a: A, s: S, /) -> S:
        return self._set(a)

    def modify(self, f: Callable[[A], A], /) -> Callable[[S], S]:
        return lambda s: self._set(f(self._get(s)))


class Id[T](Iso[T, T]):
    """The identity optic on ``T``, where a chain starts (Effect's
    ``Optic.id<T>()``): ``Id[User]().key("name")``."""

    def __init__(self) -> None:
        super().__init__((), same, same)


def _is_not_none(value: object) -> bool:
    return value is not None


def _like(source: Sequence[Any], items: list[Any]) -> Sequence[Any]:
    """``items`` in the container type of ``source`` (a tuple stays one)."""
    return tuple(items) if isinstance(source, tuple) else items


def _picker(keys: tuple[Hashable, ...], keep: bool) -> Callable[[Any], dict[Any, Any]]:
    wanted = set(keys)
    return lambda s: {k: v for k, v in s.items() if (k in wanted) == keep}


def _merger(keys: tuple[Hashable, ...], keep: bool) -> Callable[[Any, Any], dict[Any, Any]]:
    wanted = set(keys)

    def merge(part: dict[Any, Any], s: Any) -> dict[Any, Any]:
        return {**{k: v for k, v in s.items() if (k in wanted) != keep}, **part}

    return merge


def make(steps: tuple[Step, ...]) -> Optional[Any, Any]:
    """The optic of ``steps``, of their composed kind."""
    if not steps:
        return Id[Any]()
    kind: Kind = kind_of(steps)
    if len(steps) == 1:
        get, set = steps[0].get, steps[0].set
    else:
        get, set = compile_get(steps, kind), compile_set(steps, kind)
    match kind:
        case "Iso":
            return Iso(steps, get, set)
        case "Lens":
            return Lens(steps, get, set)
        case "Prism":
            return Prism(steps, get, set)
        case "Optional":
            return Optional(steps, get, set)


def make_iso[T, B](get: Callable[[T], B], set: Callable[[B], T], /) -> Iso[T, B]:
    """An ``Iso`` from two conversions that lose nothing (Effect's ``makeIso``)."""
    return cast("Iso[T, B]", make((Step("Iso", get, set),)))


def make_lens[T, B](get: Callable[[T], B], replace: Callable[[B, T], T], /) -> Lens[T, B]:
    """A ``Lens`` from a getter and a replacer (Effect's ``makeLens``)."""
    return cast("Lens[T, B]", make((Step("Lens", get, replace),)))


def make_prism[T, B](
    get_result: Callable[[T], Result[B, Issue]], set: Callable[[B], T], /
) -> Prism[T, B]:
    """A ``Prism`` from a getter that may fail and a builder (Effect's ``makePrism``)."""
    return cast("Prism[T, B]", make((Step("Prism", get_result, set),)))


def make_optional[T, B](
    get_result: Callable[[T], Result[B, Issue]],
    replace_result: Callable[[B, T], Result[T, Issue]],
    /,
) -> Optional[T, B]:
    """An ``Optional`` from a getter and a replacer that may each fail
    (Effect's ``makeOptional``)."""
    return cast("Optional[T, B]", make((Step("Optional", get_result, replace_result),)))
