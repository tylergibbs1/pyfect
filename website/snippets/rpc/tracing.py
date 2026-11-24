import pyfect as fx
from pyfect import rpc
from pyfect import schema as S
from pyfect.rpc import test as rpc_test
from pyfect.tracer import CurrentTracer, NativeSpan, SpanRequest, Tracer


class Prices(rpc.RpcGroup):
    # Called every second: no automatic client or server span.
    quote = rpc.make("Quote", success=S.Number).annotate(rpc.TracingEnabled, "none")
    # Only a server span, a child of the caller's span.
    reprice = rpc.make("Reprice").annotate(rpc.TracingEnabled, "server")


def quote(request: rpc.RpcRequest[None]) -> fx.Effect[float]:
    lookup = fx.succeed(9.5)
    parent = request.remote_parent_span  # the caller's span, sent by the client
    return lookup if parent is None else lookup.with_span("price lookup", parent=parent)


PricesLive = Prices.to_layer(
    Prices.handlers().handle(Prices.quote)(quote).handle(Prices.reprice)(lambda _: fx.void)
)

spans: list[NativeSpan] = []


def record(request: SpanRequest) -> NativeSpan:
    span = NativeSpan(request)
    spans.append(span)
    return span


@fx.fn
def checkout():
    client = yield from rpc_test.make_client(Prices, layer=PricesLive)
    yield from client.quote()
    yield from client.reprice()


fx.run_main(
    fx.scoped(checkout().with_span("checkout")).pipe(
        fx.provide_service(CurrentTracer, Tracer.make(record))
    )
)
names = {span.span_id: span.name for span in spans}
for span in spans:
    parent = span.parent
    print(span.name, span.kind, "<-", None if parent is None else names[parent.span_id])
