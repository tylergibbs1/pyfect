"""``help()`` shows typed signatures for the stream modules' overloaded functions.

``help()`` and ``inspect.signature`` read an overloaded function's implementation, not its
overloads, so an implementation typed with ``Any`` showed ``Any`` where pyright sees full
types (FINDINGS-sluice 14). An implementation takes the most general overload's shape
instead. ``STILL_ANY`` lists the ones not done yet: it may only shrink, so a new one with
``Any`` fails, and so does one listed here once it is fixed (remove it from the list).
"""

from __future__ import annotations

import importlib
import inspect
import re
import typing
from collections.abc import Callable, Iterator

MODULES = ("pyfect.stream", "pyfect.channel", "pyfect.sink", "pyfect.pull", "pyfect.queue")

STILL_ANY = {
    "pyfect.channel.Channel.catch_filter",
    "pyfect.channel.Channel.catch_if",
    "pyfect.channel.Channel.combine",
    "pyfect.channel.Channel.embed_input",
    "pyfect.channel.Channel.filter",
    "pyfect.channel.Channel.map_accum",
    "pyfect.channel.Channel.repeat",
    "pyfect.channel.Channel.retry",
    "pyfect.channel.callback",
    "pyfect.channel.callback_array",
    "pyfect.channel.catch_if",
    "pyfect.channel.catch_reason",
    "pyfect.channel.catch_reasons",
    "pyfect.channel.catch_tag",
    "pyfect.channel.from_iterable",
    "pyfect.channel.from_iterable_array",
    "pyfect.channel.from_iterator",
    "pyfect.channel.from_iterator_array",
    "pyfect.channel.from_pull",
    "pyfect.channel.from_queue",
    "pyfect.channel.from_queue_array",
    "pyfect.channel.provide",
    "pyfect.channel.unwrap",
    "pyfect.pull.catch_done",
    "pyfect.pull.match_effect",
    "pyfect.queue.Queue.await_done",
    "pyfect.queue.Queue.clear",
    "pyfect.queue.Queue.collect",
    "pyfect.sink.Sink.flat_map",
    "pyfect.sink.find",
    "pyfect.sink.take_while",
    "pyfect.sink.unwrap",
    "pyfect.stream.Stream.catch_filter",
    "pyfect.stream.Stream.catch_if",
    "pyfect.stream.Stream.combine",
    "pyfect.stream.Stream.combine_array",
    "pyfect.stream.Stream.peel",
    "pyfect.stream.Stream.repeat",
    "pyfect.stream.Stream.retry",
    "pyfect.stream.callback",
    "pyfect.stream.catch_if",
    "pyfect.stream.catch_reason",
    "pyfect.stream.catch_reasons",
    "pyfect.stream.catch_tag",
    "pyfect.stream.from_effect_repeat",
    "pyfect.stream.from_iterable_effect_repeat",
    "pyfect.stream.from_pull",
    "pyfect.stream.from_queue",
    "pyfect.stream.make",
    "pyfect.stream.provide",
    "pyfect.stream.scoped",
    "pyfect.stream.unwrap",
    "pyfect.stream.with_execution_plan",
    "pyfect.stream.zip_latest_all",
}

ANY = re.compile(r"\bAny\b")


def overloaded() -> Iterator[tuple[str, Callable[..., object]]]:
    """Each public overloaded function and method, by the name users reach it with."""
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        for name in module.__all__:
            value = getattr(module, name)
            if inspect.isfunction(value):
                if typing.get_overloads(value):
                    yield f"{module_name}.{name}", value
            elif inspect.isclass(value):
                for attribute in dir(value):
                    method = inspect.getattr_static(value, attribute)
                    if (
                        not attribute.startswith("_")
                        and inspect.isfunction(method)
                        and typing.get_overloads(method)
                    ):
                        yield f"{module_name}.{name}.{attribute}", method


def shows_any() -> set[str]:
    return {name for name, f in overloaded() if ANY.search(str(inspect.signature(f)))}


def test_no_new_overloaded_function_shows_any() -> None:
    assert sorted(shows_any() - STILL_ANY) == []


def test_fixed_functions_leave_the_list() -> None:
    assert sorted(STILL_ANY - shows_any()) == []


def test_the_stream_apis_users_extend_show_their_types() -> None:
    named = {
        "pyfect.stream.Stream.aggregate",
        "pyfect.stream.Stream.aggregate_within",
        "pyfect.stream.Stream.transduce",
        "pyfect.channel.from_transform",
        "pyfect.channel.from_transform_bracket",
        "pyfect.stream.transform_pull",
        "pyfect.stream.transform_pull_bracket",
        "pyfect.sink.make",
    }
    found = dict(overloaded())
    assert named <= found.keys()
    assert sorted(named & STILL_ANY) == []
