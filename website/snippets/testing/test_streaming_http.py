import pyfect as fx
from pyfect import stream, testing
from pyfect.errors import Done
from pyfect.http import router, server_response
from pyfect.queue import Queue


def events_route(events: Queue[bytes, Done]):
    """A route streaming whatever the test puts on `events`."""
    body = stream.from_queue(events)
    return router.add(
        "GET", "/events", fx.succeed(server_response.stream(body, content_type="text/event-stream"))
    )


@testing.effect
def test_reads_each_event_while_the_handler_is_still_writing():
    events = Queue[bytes, Done]()
    client = yield from router.in_memory_client(events_route(events))
    response = yield from client.get("http://localhost/events")
    next_chunk = yield from response.stream.to_pull()

    yield from events.offer(b"data: first\n\n")
    assert (yield from next_chunk) == (b"data: first\n\n",)
    yield from events.offer(b"data: second\n\n")
    assert (yield from next_chunk) == (b"data: second\n\n",)
