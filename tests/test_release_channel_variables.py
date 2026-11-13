"""Channel and stream loops that switch pulls let go of what they handled
once the run ends, without the cycle collector (see
``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from _closure_release import Handled, assert_freed_after_run

from pyfect import schedule, stream


def _source(value: Handled) -> stream.Stream[Handled]:
    return stream.make(value, Handled())


def test_flat_map_frees_the_inner_stream_it_stopped_in() -> None:
    assert_freed_after_run(
        lambda v: _source(v).flat_map(lambda i: stream.make(i, i)).take(1).run_drain()
    )


def test_catch_cause_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: _source(v).catch_cause(lambda _c: stream.empty).take(1).run_drain()
    )


def test_catch_all_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).catch_all(lambda _e: stream.empty).run_drain())


def test_decode_text_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: _source(v).map(lambda _: b"a").decode_text().take(1).run_drain()
    )


def test_split_lines_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).map(lambda _: "a").split_lines().run_drain())


def test_sliding_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).sliding(2).take(1).run_drain())


def test_group_adjacent_by_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).group_adjacent_by(lambda _: 1).run_drain())


def test_drop_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).rechunk(1).drop(1).run_drain())


def test_drop_right_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).rechunk(1).drop_right(1).run_drain())


def test_drop_while_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).rechunk(1).drop_while(lambda i: i is v).run_drain())


def test_repeat_elements_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).repeat_elements(schedule.recurs(1)).run_drain())


def test_repeat_elements_frees_the_item_it_repeats() -> None:
    assert_freed_after_run(
        lambda v: _source(v).repeat_elements(schedule.forever).take(1).run_drain()
    )


def test_concat_frees_the_first_stream_it_stopped_in() -> None:
    assert_freed_after_run(
        lambda v: stream.make(v, Handled()).concat(stream.never).take(1).run_drain()
    )


def test_or_else_if_empty_frees_the_stream_it_stopped_in() -> None:
    assert_freed_after_run(
        lambda v: (
            stream.make(v, Handled())
            .concat(stream.never)
            .or_else_if_empty(lambda: stream.empty)
            .take(1)
            .run_drain()
        )
    )
