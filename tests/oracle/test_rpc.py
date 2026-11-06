"""Ports of Effect's rpc/Rpc.test.ts. Each test's docstring is the Effect
test title, prefixed by its describe block.

A handler takes one ``RpcRequest`` (payload, client, request id,
headers); ``Option`` results are ``StreamSchemas | None``; JS arrays
encode to tuples. Effect's ``Schema.Any`` defect schema is ``S.Any``, keeping the defect's
whole JSON value.
"""

from pyfect import effect, testing
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.exit import Failure
from pyfect.http.headers import Headers
from pyfect.rpc import (
    RpcGroup,
    RpcRequest,
    ServerClient,
    access_handler,
    exit_schema,
    make,
    rpc_schema,
    to_layer_handler,
)


class TestGroup(RpcGroup):
    one = make("one")
    two = make("two", success=S.String)


@testing.effect
def test_can_implement_a_single_handler():
    """Rpc / can implement a single handler"""
    import pyfect as fx

    two_handler = to_layer_handler(TestGroup.two, lambda _: effect.succeed("two"))
    handler = yield from access_handler(TestGroup.two).pipe(fx.provide(two_handler))
    result = yield from handler(RpcRequest(None, ServerClient(1), "1", Headers(), TestGroup.two))
    assert result == "two"


def test_exit_schema_uses_custom_defect_schema() -> None:
    """Rpc / exitSchema uses custom defect schema"""
    # Effect's ``Schema.Any`` defect: the defect's JSON value, kept whole.
    rpc = make("customDefect", success=S.String, defect=S.Any)
    schema = exit_schema(rpc)
    error = {"message": "boom", "stack": "Error: boom\n  at foo.ts:1", "code": 42}
    round_tripped = S.decode_sync(schema)(S.encode_sync(schema)(Exit.die(error)))
    assert isinstance(round_tripped, Failure)
    assert round_tripped.cause.squash() == error


def test_json_encoded_interrupt_exits_use_null_for_a_missing_fiber_id() -> None:
    """Rpc / JSON-encoded interrupt exits use null for a missing fiberId"""
    codec = S.to_codec_json(exit_schema(make("probe")))
    encoded = S.encode_sync(codec)(Exit.interrupt())
    assert encoded == {"_tag": "Failure", "cause": ({"_tag": "Interrupt", "fiberId": None},)}
    decoded = S.decode_sync(codec)(encoded)
    assert isinstance(decoded, Failure)
    assert decoded.cause.interruptors == frozenset()
    assert decoded.cause.has_interrupts_only
    assert S.encode_sync(codec)(decoded) == encoded


def test_get_stream_schemas_returns_option() -> None:
    """Rpc / RpcSchema.getStreamSchemas returns Option"""
    plain = make("plainSchemas", success=S.String)
    stream = make("streamSchemas", success=S.String, error=S.Number, stream=True)
    assert rpc_schema.get_stream_schemas(plain.success_schema) is None
    some = rpc_schema.get_stream_schemas(stream.success_schema)
    assert some is not None
    assert some.success is S.String
    assert some.error is S.Number
