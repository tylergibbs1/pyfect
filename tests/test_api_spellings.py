"""How each combinator of ``Effect`` and ``Schedule`` is spelled.

Effect writes every combinator data-last for ``.pipe``; pyfect's primary
spelling is a method, and a combinator that removes something from a type
is a curried function only (a method binds ``self`` first and removes the
wrong thing; CLAUDE.md). Where Effect's own habit is a pipeable that
pyright types as well as the method (a unary combinator such as
``Schedule.jittered``, and ``catch_all``, Effect's ``catch``), both exist.
DOGFOOD B7: ``fx.catch_all`` and ``schedule.jittered`` were guessed and
missing. Each name below says which spelling is intended; adding a method,
or a pipeable of a name listed here, without deciding here fails. Stream,
Channel and Layer spell a combinator they share with Effect as Effect does
(``stream.catch_all`` was missing too).
"""

import inspect
from typing import Literal

import pyfect as fx
from pyfect import schedule
from pyfect._core import Effect
from pyfect.schedule import Schedule

type Spelling = Literal["method", "pipe", "both"]

_EFFECT_PIPE: dict[str, Spelling] = dict.fromkeys(
    (
        "catch_no_such_element",
        "catch_reason",
        "catch_reasons",
        "catch_tag",
        "provide",
        "provide_context",
        "provide_service",
        "provide_service_effect",
        "scoped",
        "set_context",
        "tx",
        "unwrap_reason",
        "update_context",
        "with_execution_plan",
    ),
    "pipe",
)

_EFFECT_BOTH: dict[str, Spelling] = dict.fromkeys(("catch_all", "catch_if"), "both")

_EFFECT_METHODS: dict[str, Spelling] = dict.fromkeys(
    (
        "catch_eager",
        "flat_map_eager",
        "map_both_eager",
        "map_eager",
        "map_error_eager",
        "match_cause_eager",
        "match_cause_effect_eager",
        "match_eager",
        "on_exit_primitive",
        "replicate",
        "and_then",
        "annotate_logs",
        "annotate_spans",
        "as_",
        "as_some",
        "as_void",
        "await_all_children",
        "cached",
        "cached_invalidate_with_ttl",
        "cached_with_ttl",
        "catch_cause",
        "catch_cause_filter",
        "catch_cause_if",
        "catch_defect",
        "catch_filter",
        "delay",
        "ensuring",
        "eventually",
        "exit",
        "filter_or_else",
        "filter_map_or_else",
        "filter_map_or_fail",
        "filter_or_fail",
        "is_failure",
        "is_success",
        "flat_map",
        "flatten",
        "flip",
        "forever",
        "fork",
        "fork_daemon",
        "fork_in",
        "fork_scoped",
        "head",
        "ignore",
        "ignore_cause",
        "interruptible",
        "link_spans",
        "map",
        "map_both",
        "map_error",
        "match",
        "match_cause",
        "match_cause_effect",
        "match_effect",
        "on_error",
        "on_error_filter",
        "on_error_if",
        "on_exit",
        "on_exit_filter",
        "on_exit_if",
        "on_interrupt",
        "option",
        "or_die",
        "or_else_succeed",
        "race",
        "race_first",
        "repeat",
        "repeat_or_else",
        "replicate_effect",
        "result",
        "retry",
        "retry_or_else",
        "sandbox",
        "schedule",
        "schedule_from",
        "tap",
        "tap_cause",
        "tap_cause_filter",
        "tap_cause_if",
        "tap_defect",
        "tap_error",
        "tap_error_tag",
        "timed",
        "timeout",
        "timeout_option",
        "timeout_or_else",
        "track",
        "track_defects",
        "track_duration",
        "track_errors",
        "track_successes",
        "uninterruptible",
        "update_service",
        "when",
        "with_error_reporting",
        "with_log_span",
        "with_logger",
        "with_parent_span",
        "with_span",
        "with_span_scoped",
        "with_tracer",
        "with_tracer_enabled",
        "with_tracer_timing",
        "zip",
        "zip_with",
    ),
    "method",
)

EFFECT: dict[str, Spelling] = _EFFECT_PIPE | _EFFECT_BOTH | _EFFECT_METHODS

_SCHEDULE_METHODS: dict[str, Spelling] = dict.fromkeys(
    (
        "add_delay",
        "concat",
        "concat_result",
        "map",
        "map_effect",
        "modify_delay",
        "tap",
        "up_to",
        "while_",
        "while_effect",
    ),
    "method",
)

_SCHEDULE_BOTH: dict[str, Spelling] = dict.fromkeys(("jittered", "passthrough"), "both")

SCHEDULE: dict[str, Spelling] = _SCHEDULE_METHODS | _SCHEDULE_BOTH

# Not combinators: ``pipe`` itself, and the frame flag every effect carries.
_NOT_COMBINATORS = frozenset({"pipe"})


def _methods(cls: type) -> set[str]:
    return {n for n in dir(cls) if not n.startswith("_")} - _NOT_COMBINATORS


def _functions(module: object, exported: list[str]) -> set[str]:
    return {n for n in exported if inspect.isfunction(getattr(module, n, None))}


def _actual(methods: set[str], functions: set[str], names: set[str]) -> dict[str, Spelling]:
    def spelling(name: str) -> Spelling:
        if name in methods:
            return "both" if name in functions else "method"
        return "pipe"

    return {name: spelling(name) for name in (methods | (functions & names))}


def test_every_effect_combinator_has_its_intended_spelling():
    actual = _actual(_methods(Effect), _functions(fx, fx.__all__), set(EFFECT))
    assert actual == EFFECT


def test_every_schedule_combinator_has_its_intended_spelling():
    actual = _actual(_methods(Schedule), _functions(schedule, schedule.__all__), set(SCHEDULE))
    assert actual == SCHEDULE


def test_catch_all_pipes_and_recovers_every_typed_error():
    class Boom(fx.TaggedError):
        pass

    def recover(e: Boom) -> fx.Effect[str]:
        return fx.succeed(f"recovered {type(e).__name__}")

    eff = fx.fail(Boom()).pipe(fx.catch_all(recover))
    assert fx.run_blocking(eff) == "recovered Boom"
    assert fx.run_blocking(fx.succeed("fine").pipe(fx.catch_all(recover))) == "fine"


def test_catch_all_pipeable_lets_a_defect_through_like_the_method():
    def recover(_e: object) -> fx.Effect[int]:
        return fx.succeed(1)

    boom = ValueError("x")
    exit_ = fx.run_blocking_exit(fx.die(boom).pipe(fx.catch_all(recover)))
    assert isinstance(exit_, fx.Failure) and exit_.cause.defects == (boom,)


def test_jittered_and_passthrough_pipe_as_in_effect():
    s = schedule.spaced("1 second").pipe(schedule.jittered)
    assert isinstance(s, Schedule)
    assert isinstance(schedule.recurs(2).pipe(schedule.passthrough), Schedule)


def test_stream_channel_and_layer_spell_effects_combinators_as_effect_does():
    # A combinator Stream, Channel or Layer shares with Effect has Effect's
    # spelling, so ``stream.catch_all`` is there when ``fx.catch_all`` is.
    from pyfect import channel, layer, stream
    from pyfect.channel import Channel
    from pyfect.layer import Layer
    from pyfect.stream import Stream

    mismatched: dict[str, tuple[Spelling, Spelling]] = {}
    for module, cls in ((stream, Stream), (channel, Channel), (layer, Layer)):
        actual = _actual(_methods(cls), _functions(module, module.__all__), set(EFFECT))
        mismatched |= {
            f"{module.__name__}.{name}": (spelling, EFFECT[name])
            for name, spelling in actual.items()
            if name in EFFECT and spelling != EFFECT[name]
        }
    assert mismatched == {}


def test_catch_all_pipes_on_streams_channels_and_layers():
    from pyfect import channel, layer, stream

    class Boom(fx.TaggedError):
        pass

    def to_zero(_e: Boom) -> stream.Stream[int]:
        return stream.succeed(0)

    s = stream.fail(Boom()).pipe(stream.catch_all(to_zero))
    assert fx.run_blocking(s.run_collect()) == [0]

    def to_one(_e: Boom) -> channel.Channel[int]:
        return channel.succeed(1)

    ch = channel.fail(Boom()).pipe(channel.catch_all(to_one))
    assert fx.run_blocking(ch.run_collect()) == [1]

    class Port(fx.Tag[int]): ...

    def fallback(_e: Boom) -> layer.Layer[Port]:
        return layer.succeed(Port, 8080)

    live = layer.effect(Port, fx.fail(Boom())).pipe(layer.catch_all(fallback))
    assert fx.run_blocking(Port().pipe(fx.provide(live))) == 8080
