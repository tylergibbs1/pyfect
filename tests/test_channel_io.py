"""Channels fed from or into queues, pubsubs, callbacks and schedules, and
the text channels, beyond ``Channel.test.ts``.

Expected values were printed by Effect's ``Channel.ts`` under Node (see
docs/PARITY.md).
"""

import pyfect as fx
from pyfect import channel, schedule, testing
from pyfect.pubsub import PubSub
from pyfect.queue import Queue

# --- sources ------------------------------------------------------------------------


@testing.effect
def test_from_queue_takes_until_the_queue_ends():
    queue = Queue[int, fx.Done]()
    yield from queue.offer_all([1, 2])
    yield from queue.end()
    assert (yield from channel.from_queue(queue).run_collect()) == [1, 2]


@testing.effect
def test_from_queue_array_takes_everything_waiting():
    queue = Queue[int, fx.Done]()
    yield from queue.offer_all([1, 2])
    yield from queue.end()
    assert (yield from channel.from_queue_array(queue).run_collect()) == [(1, 2)]


@testing.effect
def test_from_subscription_ends_when_the_pubsub_shuts_down():
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish_all([1, 2])
    yield from pubsub.shutdown()
    assert (yield from channel.from_subscription(subscription).run_collect()) == []


@testing.live
def test_from_pubsub_array_keeps_what_reached_a_waiting_reader_before_shutdown():
    pubsub = yield from PubSub[int].unbounded()
    reader = yield from channel.from_pubsub_array(pubsub).run_collect().fork()
    yield from fx.sleep(0.01)
    yield from pubsub.publish_all([1, 2])
    yield from pubsub.shutdown()
    assert (yield from reader.join()) == [(1, 2)]


@testing.effect
def test_callback_writes_what_it_offers():
    offered = channel.callback(lambda q: q.offer_all([1, 2, 3]).and_then(q.end()))
    assert (yield from offered.run_collect()) == [1, 2, 3]
    in_chunks = channel.callback_array(lambda q: q.offer_all([1, 2, 3]).and_then(q.end()))
    assert (yield from in_chunks.run_collect()) == [(1, 2, 3)]


@testing.effect
def test_from_schedule_writes_each_output_and_ends_with_the_last():
    assert (yield from channel.from_schedule(schedule.recurs(3)).run_collect()) == [0, 1, 2]
    assert (yield from channel.from_schedule(schedule.recurs(3)).run_drain()) == 3


# --- sinks --------------------------------------------------------------------------


@testing.effect
def test_to_queue_ends_the_queue_as_the_channel_ends():
    queue = yield from channel.from_iterable([1, 2, 3]).to_queue(capacity=1)
    assert (yield from queue.collect()) == [1, 2, 3]


@testing.effect
def test_to_queue_fails_the_queue_as_the_channel_fails():
    failing = channel.from_iterable([1]).concat(channel.fail("x"))
    queue = yield from failing.to_queue(capacity="unbounded")
    assert (yield from queue.collect().exit()) == fx.exit.fail("x")


@testing.effect
def test_run_into_queue_ends_the_queue():
    queue = Queue[int, fx.Done]()
    yield from channel.from_iterable([1, 2]).run_into_queue(queue)
    assert (yield from queue.collect()) == [1, 2]


@testing.effect
def test_run_into_pubsub_publishes_and_succeeds_with_the_end_value():
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    source = channel.from_iterable([1, 2]).concat(channel.end("D"))
    assert (yield from source.run_into_pubsub(pubsub)) == "D"
    assert (yield from subscription.take_all()) == [1, 2]
    assert not (yield from pubsub.is_shutdown())


@testing.effect
def test_to_pubsub_take_replays_through_from_pubsub_take():
    pubsub = yield from channel.from_iterable([(1, 2), (3,)]).to_pubsub_take(capacity="unbounded")
    assert (yield from channel.from_pubsub_take(pubsub).run_collect()) == [(1, 2), (3,)]


# --- text ---------------------------------------------------------------------------


@testing.effect
def test_split_lines_splits_at_every_kind_of_line_break():
    chunks = [("a\r", "\nb\nc"), ("d\re", ""), ("\r",), ("\nf",)]
    lines = channel.from_iterable(chunks).pipe_to(channel.split_lines())
    assert (yield from lines.run_collect()) == [("a", "b"), ("cd",), ("e",), ("f",)]


@testing.effect
def test_split_lines_keeps_empty_lines():
    lines = channel.from_iterable([("\n\n", "x")]).pipe_to(channel.split_lines())
    assert (yield from lines.run_collect()) == [("", ""), ("x",)]


@testing.effect
def test_decode_text_drops_a_byte_order_mark_unless_ignore_bom():
    source = channel.from_iterable([(b"\xef\xbb\xbfa",)])
    assert (yield from source.pipe_to(channel.decode_text()).run_collect()) == [("a",)]
    kept = source.pipe_to(channel.decode_text(ignore_bom=True))
    assert (yield from kept.run_collect()) == [("﻿a",)]


@testing.effect
def test_encode_text_encodes_utf_8():
    encoded = channel.from_iterable([("héllo", "x")]).pipe_to(channel.encode_text())
    assert (yield from encoded.run_collect()) == [("héllo".encode(), b"x")]
