import pyfect as fx
from pyfect import tracer


@fx.fn("get_user")  # every call runs inside a span named get_user
def get_user(user_id: str):
    yield from fx.annotate_current_span("user.id", user_id)
    yield from fx.sleep(0.01).with_span("db.query")
    return (yield from fx.current_span())


span = fx.run_blocking(get_user("42").with_span("GET /users/42").or_die())

assert span.name == "get_user"
assert span.attributes["user.id"] == "42"
assert isinstance(span.parent, tracer.NativeSpan) and span.parent.name == "GET /users/42"
