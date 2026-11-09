"""The unencrypted event log server passes the presented signing public key
to ``authorize_identity``, and ``derive_signing_public_key`` gives the key an
identity presents, so a deployment can record it at provisioning time and
reject any other key, also on first use (Effect 4.1.2's
``authorizeIdentity({ publicKey, signingPublicKey })`` and
``EventLogSessionAuth.deriveSigningPublicKey``; dogfood apps #9).
"""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.effect import Effect
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.eventlog.event_log_session_auth import (
    SessionAuthPayload,
    derive_signing_public_key,
    sign_session_auth_payload,
)
from pyfect.redacted import value as reveal
from pyfect.rpc import test as rpc_test


class _PinnedKeys(U.EventLogServerAuthorizationService):
    """Allows an identity only with the signing key recorded for it."""

    def __init__(self) -> None:
        self.pinned: dict[str, bytes] = {}
        self.seen: list[tuple[str, bytes]] = []

    def authorize_write(self, **_: Any) -> Effect[None, U.EventLogServerAuthError]:
        return fx.void

    def authorize_read(self, **_: Any) -> Effect[None, U.EventLogServerAuthError]:
        return fx.void

    def authorize_identity(
        self, *, public_key: str, signing_public_key: bytes
    ) -> Effect[None, U.EventLogServerAuthError]:
        self.seen.append((public_key, signing_public_key))
        if self.pinned.get(public_key) == signing_public_key:
            return fx.void
        return fx.fail(U.EventLogServerAuthError("Forbidden", public_key, message="Unknown key"))


class _Stores(U.StoreMappingService):
    def resolve(self, *, public_key: str, store_id: StoreId) -> Effect[StoreId, Any]:
        return fx.succeed(store_id)

    def has_store(self, **_: Any) -> Effect[bool, Any]:
        return fx.succeed(True)


def _client(authorization: U.EventLogServerAuthorizationService):
    storage = yield from U.make_storage_memory
    handlers = (
        U.layer_rpc_handlers.pipe(fx.layer.provide(fx.layer.succeed(U.Storage, storage)))
        .pipe(fx.layer.provide(L.layer_registry))
        .pipe(fx.layer.provide(fx.layer.succeed(U.StoreMapping, _Stores())))
        .pipe(fx.layer.provide(fx.layer.succeed(U.EventLogServerAuthorization, authorization)))
    )
    return (yield from rpc_test.make_client(M.EventLogRemoteRpcs).pipe(fx.provide(handlers)))


def _authenticate(identity: L.IdentityService, hello: M.HelloResponse):
    material = yield from make_get_identity_root_secret_material()(identity)
    signature = yield from sign_session_auth_payload(
        SessionAuthPayload(
            remote_id=hello.remote_id,
            challenge=hello.challenge,
            public_key=identity.public_key,
            signing_public_key=material.signing_public_key,
        ),
        reveal(material.signing_private_key),
    )
    return M.Authenticate(
        public_key=identity.public_key,
        signing_public_key=material.signing_public_key,
        signature=signature,
        algorithm="Ed25519",
    )


@testing.effect
def test_derive_signing_public_key_is_the_key_an_identity_presents():
    def body():
        identity = yield from L.make_identity
        derived = yield from derive_signing_public_key(identity)
        material = yield from make_get_identity_root_secret_material()(identity)
        assert derived == material.signing_public_key
        assert len(derived) == 32

    yield from fx.gen(body).pipe(fx.provide(layer_subtle))


@testing.effect
def test_authorize_identity_gets_the_presented_signing_key_and_can_pin_it():
    def body():
        policy = _PinnedKeys()
        client = yield from _client(policy)
        known = yield from L.make_identity
        policy.pinned[known.public_key] = yield from derive_signing_public_key(known)
        hello = yield from client.hello()
        yield from client.authenticate((yield from _authenticate(known, hello)))
        assert policy.seen == [(known.public_key, policy.pinned[known.public_key])]

        stranger = yield from L.make_identity
        hello = yield from client.hello()
        error = yield from client.authenticate((yield from _authenticate(stranger, hello))).flip()
        assert isinstance(error, M.EventLogProtocolError)
        assert error.code == "Forbidden"

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer_subtle))
