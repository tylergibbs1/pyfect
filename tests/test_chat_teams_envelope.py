"""Port of Effect's ``packages/chat/teams/test/envelope.test.ts``: button and
dialog tokens are bound to their conversation, user and keys."""

from __future__ import annotations

from _teams_fake import INTERACTION_KEY, OTHER_KEY, Gen

import pyfect as fx
from pyfect import layer, testing
from pyfect.chat import chat_ui as U
from pyfect.chat.teams import _envelope
from pyfect.crypto.native import layer_digest, layer_mac

CRYPTO = layer.merge(layer_digest, layer_mac)
OPTIONS = {"app_id": "app-1", "tenant_id": "tenant-1"}
CONVERSATION = "19:abc@thread.tacv2"


@testing.effect
def test_refuses_a_button_from_another_conversation_a_tampered_token_and_an_unknown_kid():
    """envelope / refuses a button from another conversation, a tampered token and an unknown kid"""

    @fx.gen
    def program() -> Gen[None]:
        envelope = yield from _envelope.make(**OPTIONS, keys=[INTERACTION_KEY])
        token = yield from envelope.sign_button(CONVERSATION, _envelope.Button("approve", "42"))
        assert (
            yield from envelope.verify_button(token, conversation_id="19:other@thread.tacv2")
        ) is None

        header, payload, signature = token.split(".")
        swapped = "BA" if signature.endswith("AA") else "AA"
        tampered = f"{header}.{payload}.{signature[:-2]}{swapped}"
        assert (yield from envelope.verify_button(tampered, conversation_id=CONVERSATION)) is None

        other = yield from _envelope.make(**OPTIONS, keys=[OTHER_KEY])
        unknown_kid = yield from other.sign_button(CONVERSATION, _envelope.Button("approve"))
        assert (
            yield from envelope.verify_button(unknown_kid, conversation_id=CONVERSATION)
        ) is None

        rotated = yield from _envelope.make(**OPTIONS, keys=[OTHER_KEY, INTERACTION_KEY])
        verified = yield from rotated.verify_button(token, conversation_id=CONVERSATION)
        assert verified == _envelope.Button("approve", "42")

    return program.pipe(fx.provide(CRYPTO))


@testing.effect
def test_binds_a_dialog_to_its_user_and_reply_chain_and_a_submit_to_its_definition():
    """envelope / binds a dialog to its user and reply chain, and a submit to its definition"""
    modal = U.Modal(
        id="deploy",
        title="Deploy",
        metadata="m",
        elements=(
            U.SelectInput(
                id="env", label="Env", options=(U.SelectOption(label="Prod", value="prod"),)
            ),
            U.TextInput(id="note", label="Note", optional=True),
        ),
    )

    @fx.gen
    def program() -> Gen[None]:
        envelope = yield from _envelope.make(**OPTIONS, keys=[INTERACTION_KEY])
        opened = f"{CONVERSATION};messageid=123"
        token = yield from envelope.sign_dialog(
            _envelope.Dialog(conversation_id=opened, modal=modal, message_id="123"), user_id="u1"
        )
        assert (
            yield from envelope.verify_dialog(token, conversation_id=opened, user_id="u2")
        ) is None
        # The same channel, another reply chain: refused, so a submit keeps the click's origin.
        moved = f"{CONVERSATION};messageid=456"
        assert (
            yield from envelope.verify_dialog(token, conversation_id=moved, user_id="u1")
        ) is None
        verified = yield from envelope.verify_dialog(token, conversation_id=opened, user_id="u1")
        assert verified == _envelope.Dialog(conversation_id=opened, modal=modal, message_id="123")
        submitted = {"effect": token, "env": "prod", "note": ""}
        assert _envelope.validate_submission(modal, submitted) == {"env": "prod"}
        assert _envelope.validate_submission(modal, {"env": "staging"}) is None

    return program.pipe(fx.provide(CRYPTO))


@testing.effect
def test_a_dialog_token_expires_after_its_ttl():
    """envelope / a dialog token expires after its ttl"""
    modal = U.Modal(id="m", title="M", elements=(U.TextInput(id="a", label="A"),))

    @fx.gen
    def program() -> Gen[None]:
        envelope = yield from _envelope.make(**OPTIONS, keys=[INTERACTION_KEY])
        dialog = _envelope.Dialog(conversation_id=CONVERSATION, modal=modal)
        token = yield from envelope.sign_dialog(dialog, user_id="u1")
        assert (
            yield from envelope.verify_dialog(token, conversation_id=CONVERSATION, user_id="u1")
        ) == dialog
        yield from testing.adjust("2 hours")
        assert (
            yield from envelope.verify_dialog(token, conversation_id=CONVERSATION, user_id="u1")
        ) is None

    return program.pipe(fx.provide(CRYPTO))


def test_a_token_longer_than_any_signed_one_is_refused_unread():
    """envelope / the longest token is computed from the limits"""
    assert _envelope.MAX_TOKEN_LENGTH > 16_000
