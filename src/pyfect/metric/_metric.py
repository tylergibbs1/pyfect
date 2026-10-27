"""The ``Metric`` type: a named, attributed measurement whose series live
in the ``MetricRegistry`` of the fiber that updates it.

A metric is a description, like an effect: two metrics with the same
kind, id, description and attributes share one series. Each update looks
the series up in the current registry, with the current contextual
attributes merged in, so one metric can feed many registries and many
attribute sets.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Final, Generic, Self, TypeVar, final

from pyfect._core import Effect
from pyfect.context import Context
from pyfect.exit import Success
from pyfect.metric._refs import (
    Attributes,
    CurrentMetricAttributes,
    Hooks,
    Metadata,
    MetricKey,
    MetricRegistry,
    Registry,
    make_key,
    merge,
    to_record,
)

if TYPE_CHECKING:
    from pyfect._effect_base import Step
    from pyfect._fiber import Fiber
    from pyfect.metric._state import MetricType

In_contra = TypeVar("In_contra", contravariant=True)
State_co = TypeVar("State_co", covariant=True)


class Metric(ABC, Generic[In_contra, State_co]):
    """A metric taking ``In`` updates and holding a ``State``. Make one
    with ``metric.counter``, ``gauge``, ``frequency``, ``histogram``,
    ``summary`` or ``timer``."""

    __slots__ = ("attributes", "description", "id", "type")

    def __init__(
        self,
        kind: MetricType,
        id: str,
        description: str | None,
        attributes: Mapping[str, str] | None,
    ) -> None:
        self.type: Final[MetricType] = kind
        self.id: Final = id
        self.description: Final = description
        self.attributes: Final = attributes

    @abstractmethod
    def unsafe_value(self, context: Context) -> State_co:
        """The state of the series ``context`` selects."""

    @abstractmethod
    def unsafe_update(self, input: In_contra, context: Context) -> None:
        """Update the series ``context`` selects."""

    @abstractmethod
    def unsafe_modify(self, input: In_contra, context: Context) -> None:
        """Modify the series ``context`` selects (a gauge adds ``input``;
        the other kinds update)."""

    @abstractmethod
    def unsafe_remove(self, context: Context) -> None:
        """Drop the series ``context`` selects from its registry."""

    @abstractmethod
    def _register(self, context: Context, get: Callable[[Context], Any]) -> Registration: ...

    def value(self) -> Effect[State_co]:
        """The state of this metric's series in the current registry."""
        return WithContext(self.unsafe_value)

    def update(self, input: In_contra) -> Effect[None]:
        """Update the series: a counter adds, a gauge sets, a frequency
        counts the word, a histogram or summary records the value."""
        return WithContext(lambda context: self.unsafe_update(input, context))

    def modify(self, input: In_contra) -> Effect[None]:
        """Modify the series: a gauge adds ``input`` to its value; the
        other kinds update."""
        return WithContext(lambda context: self.unsafe_modify(input, context))

    def remove(self) -> Effect[None]:
        """Drop the series for the current attributes; the next update
        starts it afresh."""
        return WithContext(self.unsafe_remove)

    def map_input[In2](self, f: Callable[[In2], In_contra]) -> Metric[In2, State_co]:
        """The same series, updated with ``f(input)``."""
        return _Transform(self, lambda input, _: f(input), _same)

    def with_constant_input(self, input: In_contra) -> Metric[object, State_co]:
        """The same series, updated with ``input`` whatever it is given."""
        return _Transform(self, lambda _, __: input, _same)

    def with_attributes(self, attributes: Attributes) -> Metric[In_contra, State_co]:
        """The series with ``attributes`` added; they win over the
        contextual attributes and the metric's own."""
        return _Transform(self, _pass_input, _adding(attributes))

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)


def unsafe_register[S](
    metric: Metric[Any, S], context: Context, get: Callable[[Context], S]
) -> Registration:
    """Make ``get`` the series ``context`` selects: snapshots and values
    call it, updates do nothing. ``remove()`` on the result drops the
    series, unless something registered it again since."""
    return metric._register(context, get)


@final
class Registration:
    __slots__ = ("_key", "_metadata", "_registry")

    def __init__(self, registry: Registry, key: MetricKey, metadata: Metadata) -> None:
        self._registry = registry
        self._key = key
        self._metadata = metadata

    def remove(self) -> None:
        if self._registry.get(self._key) is self._metadata:
            del self._registry[self._key]


_UNSET: Final[object] = object()


class Series(Metric[In_contra, State_co]):
    """A metric that owns its series: each kind says how a series starts
    (``_create_hooks``)."""

    __slots__ = ("_cache",)

    def __init__(
        self,
        kind: MetricType,
        id: str,
        description: str | None,
        attributes: Attributes | None,
    ) -> None:
        super().__init__(kind, id, description, to_record(attributes))
        # The contextual attributes last seen, and the key and attributes
        # they give; swapped as one tuple, so a reader never mixes two.
        self._cache: tuple[object, MetricKey | None, Mapping[str, str] | None] = (
            _UNSET,
            None,
            None,
        )

    @abstractmethod
    def _create_hooks(self) -> Hooks: ...

    def unsafe_value(self, context: Context) -> State_co:
        return self._hooks(context).get(context)

    def unsafe_update(self, input: In_contra, context: Context) -> None:
        self._hooks(context).update(input, context)

    def unsafe_modify(self, input: In_contra, context: Context) -> None:
        self._hooks(context).modify(input, context)

    def unsafe_remove(self, context: Context) -> None:
        key, _ = self._series(context)
        context.unsafe_get(MetricRegistry).pop(key, None)

    def _register(self, context: Context, get: Callable[[Context], Any]) -> Registration:
        key, attributes = self._series(context)
        # The registry of registration time, so removing does not depend
        # on where ``remove`` is called.
        registry = context.unsafe_get(MetricRegistry)
        metadata = self._metadata(attributes, Hooks(get, _ignore, _ignore))
        registry[key] = metadata
        return Registration(registry, key, metadata)

    def _hooks(self, context: Context) -> Hooks:
        # The registry owns the series, so it is looked up on every update.
        key, attributes = self._series(context)
        registry = context.unsafe_get(MetricRegistry)
        metadata = registry.get(key)
        if metadata is None:
            metadata = registry.setdefault(key, self._metadata(attributes, self._create_hooks()))
        return metadata.hooks

    def _series(self, context: Context) -> tuple[MetricKey, Mapping[str, str] | None]:
        """The key and attributes of the series ``context`` selects, merged
        once per contextual attribute set."""
        extra = context.unsafe_get(CurrentMetricAttributes)
        seen, key, attributes = self._cache
        if extra is not seen or key is None:
            merged = merge(self.attributes, extra)
            attributes = merged if extra else self.attributes
            key = make_key(self.type, self.id, self.description, merged)
            self._cache = (extra, key, attributes)
        return key, attributes

    def _metadata(self, attributes: Mapping[str, str] | None, hooks: Hooks) -> Metadata:
        return Metadata(self.id, self.type, self.description, attributes, hooks)


@final
class _Transform(Metric[In_contra, State_co]):
    """Another metric's series, reached through a context and input map.
    Every operation maps the context first and the input second, so
    ``with_attributes`` addresses the same series for update, remove and
    register."""

    __slots__ = ("_map_context", "_map_input", "_metric")

    def __init__(
        self,
        metric: Metric[Any, Any],
        map_input: Callable[[Any, Context], Any],
        map_context: Callable[[Context], Context],
    ) -> None:
        super().__init__(metric.type, metric.id, metric.description, metric.attributes)
        self._metric = metric
        self._map_input = map_input
        self._map_context = map_context

    def unsafe_value(self, context: Context) -> State_co:
        return self._metric.unsafe_value(self._map_context(context))

    def unsafe_update(self, input: In_contra, context: Context) -> None:
        mapped = self._map_context(context)
        self._metric.unsafe_update(self._map_input(input, mapped), mapped)

    def unsafe_modify(self, input: In_contra, context: Context) -> None:
        mapped = self._map_context(context)
        self._metric.unsafe_modify(self._map_input(input, mapped), mapped)

    def unsafe_remove(self, context: Context) -> None:
        self._metric.unsafe_remove(self._map_context(context))

    def _register(self, context: Context, get: Callable[[Context], Any]) -> Registration:
        return self._metric._register(self._map_context(context), get)


def map_input_with_context[In2, S](
    metric: Metric[Any, S], f: Callable[[In2, Context], Any]
) -> Metric[In2, S]:
    """``map_input`` with the updating fiber's context (the summary's
    clock, say)."""
    return _Transform(metric, f, _same)


def _adding(attributes: Attributes) -> Callable[[Context], Context]:
    added = to_record(attributes)
    # Merged once per contextual attribute set, so the wrapped metric
    # keeps finding its cached series key.
    cache: tuple[object, Mapping[str, str]] = (_UNSET, {})

    def map_context(context: Context) -> Context:
        nonlocal cache
        extra = context.unsafe_get(CurrentMetricAttributes)
        seen, merged = cache
        if extra is not seen:
            merged = merge(extra, added)
            cache = (extra, merged)
        return context.add(CurrentMetricAttributes, merged)

    return map_context


def _same(context: Context) -> Context:
    return context


def _pass_input(input: Any, _: Context) -> Any:
    return input


def _ignore(_input: Any, _context: Context) -> None:
    pass


@final
class WithContext[A](Effect[A]):
    """Run ``f`` with the fiber's context."""

    __slots__ = ("f",)

    def __init__(self, f: Callable[[Context], A]) -> None:
        self.f = f

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return Success(self.f(fiber._context))
