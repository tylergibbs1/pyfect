"""The initial message of RPC workers (Effect's ``RpcWorker``).

A worker client (``rpc.client.layer_protocol_worker``) can send each
worker one value before any request: provide ``InitialMessage`` with
``layer_initial_message(schema, build)``, and read it in the worker with
``initial_message(schema)``, which waits for it.
"""

from __future__ import annotations

from typing import Any

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Context, Tag
from pyfect.effect import context, fail, provide_context, provide_service, succeed
from pyfect.errors import NoSuchElementException
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.option import Option
from pyfect.rpc.server._protocol import ServerProtocol
from pyfect.workers.transferable import Collector, make_collector_unsafe

type Encoded = tuple[object, tuple[object, ...]]
"""An encoded initial message and the values to transfer with it."""


class InitialMessage(Tag[Effect[Encoded]], key="effect/rpc/RpcWorker/InitialMessage"):
    """Makes the value a worker client sends each worker first."""


def make_initial_message[A, E = Any, R = Any](
    schema: S.Codec[A, Any, Any, Any], eff: Effect[A, E, R]
) -> Effect[Encoded, E | S.SchemaError, R]:
    """Run ``eff`` and encode its value with ``schema``'s JSON codec,
    collecting its transferables."""
    require_effect(eff, "eff")
    encode = S.encode_effect(S.to_codec_json(schema))

    def encoded(value: A) -> Effect[Encoded, S.SchemaError, Any]:
        collector = make_collector_unsafe()
        return (
            encode(value)
            .pipe(provide_service(Collector, collector))
            .map(lambda data: (data, tuple(collector.clear_unsafe())))
        )

    return eff.flat_map(encoded)


def layer_initial_message[A, R = Any](
    schema: S.Codec[A, Any, Any, Any], build: Effect[A, Any, R]
) -> Layer[InitialMessage, Any, R]:
    """Provide ``InitialMessage`` from ``build``, run with the layer's
    services each time a worker spawns; an encoding failure is a defect."""
    require_effect(build, "build")

    def made(services: Context[Any]) -> Effect[Encoded]:
        return make_initial_message(schema, build).or_die().pipe(provide_context(services))

    return layer_effect(InitialMessage, context().map(made))


def _from_option(found: Option[object]) -> Effect[object, NoSuchElementException]:
    if found is None:
        return fail(NoSuchElementException())
    return succeed(found.value)


def initial_message[A](
    schema: S.Codec[A, Any, Any, Any],
) -> Effect[A, NoSuchElementException | S.SchemaError, ServerProtocol]:
    """The initial message the client sent this worker, decoded with
    ``schema``'s JSON codec; fails when the protocol has none."""
    decode = S.decode_unknown_effect(S.to_codec_json(schema))
    return (
        ServerProtocol()
        .flat_map(lambda protocol: protocol.initial_message)
        .flat_map(_from_option)
        .flat_map(decode)
    )


__all__ = [
    "Encoded",
    "InitialMessage",
    "NoSuchElementException",
    "initial_message",
    "layer_initial_message",
    "make_initial_message",
]
