"""Port of Effect's ``test/chat/ChatInteraction.test.ts``: values encode by
their schema, modals open in field order, groups route by id to typed
handlers, ``handle`` answers ``Late`` at the deadline, and ``ChatTest.interact``
keeps follow-ups to their window."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, TypedDict

import pyfect as fx
import pyfect.schema as S
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_test, chat_thread
from pyfect.chat import chat_ui as U
from pyfect.chat.chat import Chat
from pyfect.chat.chat_error import CAPABILITIES, INTERACTION_EXPIRED, ChatError, Unsupported
from pyfect.chat.chat_test import ChatTest
from pyfect.deferred import Deferred
from pyfect.duration import seconds
from pyfect.exit import Success
from pyfect.option import Some

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


class DeployValue(TypedDict):
    version: str


Deploy = S.Struct(DeployValue)
thread = chat_thread.make("test", "c1")


def clicked(id: str, value: str | None = None) -> ci.ButtonClicked:
    return ci.ButtonClicked(
        id=id, value=value, thread=thread, message_id="m1", user_id="u1", raw=None
    )


def submitted(id: str, values: dict[str, str], metadata: str | None = None) -> ci.ModalSubmitted:
    return ci.ModalSubmitted(
        id=id,
        metadata=metadata,
        values=values,
        thread=thread,
        message_id="m1",
        user_id="u1",
        raw=None,
    )


def invoked(id: str, text: str = "") -> ci.CommandInvoked:
    return ci.CommandInvoked(id=id, text=text, thread=thread, user_id="u1", raw={"id": "i1"})


def handler_with(
    *,
    click: Effect[ci.ClickReply] | None = None,
    submit: Effect[ci.SubmitReply] | None = None,
    command: Callable[[ci.CommandInvoked], ci.CommandReply] | None = None,
    refused: Callable[[ChatError], Effect[None]] | None = None,
) -> ci.HandlerService:
    return ci.HandlerService(
        click=lambda _: click if click is not None else fx.succeed(ci.ack),
        submit=lambda _: submit if submit is not None else fx.succeed(ci.close),
        command=lambda c: fx.succeed(command(c) if command is not None else ci.ack),
        refused=lambda _, error: refused(error) if refused is not None else fx.void,
    )


def test_encodes_a_value_by_its_schema():
    """encodes a value by its schema: a string-only schema as it is, anything else as JSON"""
    string_or_number = S.Union(S.String, S.Number)
    assert ci.encode_value(S.String, "v1.4.2") == "v1.4.2"
    assert ci.decode_value(S.String, '"quoted"') == Some('"quoted"')
    assert ci.encode_value(string_or_number, "123") == '"123"'
    assert ci.decode_value(string_or_number, "123") == Some(123)


def test_modal_open_builds_the_elements_in_field_order_with_encoded_metadata_and_options():
    """modal.open builds the elements in field order, with encoded metadata and options"""
    reason = ci.modal(
        "reason",
        title="Why",
        metadata=Deploy,
        fields={
            "intro": ci.text("Tell us."),
            "reason": ci.text_input(label="Reason", multiline=True, max_length=200),
            "env": ci.select_input(label="Env", value=S.Number, optional=True),
        },
    )
    opened = reason.open(
        metadata={"version": "v1"},
        options={"env": [ci.OptionOf(label="Prod", value=1)]},
        initial={"env": 1},
    )
    assert opened.modal == U.Modal(
        id="reason",
        title="Why",
        metadata='{"version":"v1"}',
        elements=(
            U.Text(text="Tell us."),
            U.TextInput(id="reason", label="Reason", multiline=True, max_length=200),
            U.SelectInput(
                id="env",
                label="Env",
                options=(U.SelectOption(label="Prod", value="1"),),
                initial="1",
                optional=True,
            ),
        ),
    )


# --- layer and groups ----------------------------------------------------------------

Approve = ci.button("approve", label="Approve", value=Deploy)
Reason = ci.modal(
    "reason",
    title="Why",
    metadata=Deploy,
    fields={
        "reason": ci.text_input(label="Reason"),
        "severity": ci.choice(label="Severity", options=[ci.OptionOf(label="Low", value="low")]),
        "note": ci.text_input(label="Note", optional=True),
    },
)
Ship = ci.command(
    "ship",
    description="Ship a version",
    argument=ci.CommandArgument(name="version", description="The version"),
)


class _Log:
    def __init__(self) -> None:
        self.seen: list[object] = []
        self.unhandled: list[str] = []


def interactions(log: _Log):
    def approve(click: ci.Click[DeployValue]) -> Effect[ci.ClickReply]:
        return fx.sync(lambda: log.seen.append(click.value)).as_(Reason.open(metadata=click.value))

    def reason(submit: ci.Submit[DeployValue]) -> Effect[ci.SubmitReply]:
        def run() -> ci.SubmitReply:
            log.seen.append({"metadata": submit.metadata, "values": dict(submit.values)})
            return ci.errors(reason="Longer.") if len(submit.values["reason"]) < 3 else ci.close

        return fx.sync(run)

    def unhandled(event: ci.Interaction, why: ci.Unhandled) -> Effect[None]:
        return fx.sync(lambda: log.unhandled.append(f"{event.id}:{why.reason}"))

    return (
        ci.group(Approve)
        .add(Reason, Ship)
        .to_layer(
            Ship.handler(
                lambda command: fx.succeed(ci.respond(markdown="Shipping " + command.text))
            ),
            Approve.handler(approve),
            Reason.handler(reason),
        )
        .pipe(layer.provide_merge(ci.layer(unhandled=unhandled)))
    )


@testing.effect
def test_routes_a_click_and_a_submit_to_the_typed_handlers():
    """layer and groups / routes a click and a submit to the typed handlers"""
    log = _Log()

    @fx.gen
    def program() -> Gen[None]:
        handler = yield from ci.Handler()
        reply = yield from handler.click(clicked("approve", Approve.of({"version": "v1"}).value))
        assert isinstance(reply, ci.OpenModal)
        sent = submitted("reason", {"reason": "ok", "severity": "low"}, reply.modal.metadata)
        assert (yield from handler.submit(sent)) == ci.errors(reason="Longer.")
        assert log.seen == [
            {"version": "v1"},
            {
                "metadata": {"version": "v1"},
                "values": {"reason": "ok", "severity": "low", "note": None},
            },
        ]

    return program.pipe(fx.provide(interactions(log)))


@testing.effect
def test_routes_a_command_to_its_handler_and_answers_an_unknown_one_ack():
    """layer and groups / routes a command to its handler, and answers an unknown one Ack"""
    log = _Log()

    @fx.gen
    def program() -> Gen[None]:
        handler = yield from ci.Handler()
        assert (yield from handler.command(invoked("ship", "v1"))) == ci.Respond(
            markdown="Shipping v1", visibility="ephemeral"
        )
        assert (yield from handler.command(invoked("nope"))) == ci.ack
        # A command and a button share one id space: a command named like a button is not
        # routed to it.
        assert (yield from handler.command(invoked("approve"))) == ci.ack
        assert log.unhandled == ["nope:UnknownId", "approve:UnknownId"]

    return program.pipe(fx.provide(interactions(log)))


@testing.effect
def test_answers_an_unknown_id_or_a_value_that_no_longer_decodes_without_a_handler():
    """layer and groups / answers an unknown id or a value that no longer decodes without a
    handler"""
    log = _Log()

    @fx.gen
    def program() -> Gen[None]:
        handler = yield from ci.Handler()
        assert (yield from handler.click(clicked("nope"))) == ci.ack
        assert (yield from handler.click(clicked("approve", "{"))) == ci.ack
        assert (yield from handler.click(clicked("reason"))) == ci.ack
        bad_choice = submitted(
            "reason", {"reason": "long enough", "severity": "high"}, '{"version":"v1"}'
        )
        assert (yield from handler.submit(bad_choice)) == ci.close
        assert log.seen == []
        assert log.unhandled == [
            "nope:UnknownId",
            "approve:InvalidValue",
            "reason:UnknownId",
            "reason:InvalidValue",
        ]

    return program.pipe(fx.provide(interactions(log)))


@testing.effect
def test_dies_on_an_id_registered_twice():
    """layer and groups / dies on an id registered twice"""
    twice = ci.group(Approve).to_layer(Approve.handler(lambda _: fx.succeed(ci.ack)))
    built = twice.pipe(layer.provide_merge(interactions(_Log())))
    exit = yield from fx.void.pipe(fx.provide(built)).exit()
    assert not isinstance(exit, Success)


# --- handle --------------------------------------------------------------------------

DEADLINE = seconds(3)


@testing.effect
def test_interrupts_the_handler_when_cancelled_during_startup():
    """handle / interrupts the handler when cancelled during startup"""
    release = yield from Deferred[ci.ClickReply].make()

    @fx.gen
    def attempts() -> Gen[None]:
        # Cancel at successive scheduler yields, including between fork and cleanup
        # registration.
        for budget in range(1, 41):
            state = {"started": False, "stopped": False}

            def start(state: dict[str, bool] = state) -> None:
                state["started"] = True

            def stop(_: None, _exit: object, state: dict[str, bool] = state) -> Effect[None]:
                return fx.sync(lambda: state.__setitem__("stopped", True))

            handler = handler_with(
                click=fx.acquire_use_release(fx.sync(start), lambda _: release.wait(), stop)
            )
            fiber = yield from (
                ci.handle(clicked("a"), DEADLINE)
                .pipe(fx.provide_service(ci.Handler, handler))
                .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
                .fork(start_immediately=True)
            )
            yield from fiber.interrupt()
            yield from testing.adjust("1 millis")
            assert not (state["started"] and not state["stopped"]), f"MaxOpsBeforeYield {budget}"

    yield from attempts.ensuring(release.succeed(ci.ack))


@testing.effect
def test_gives_late_for_a_late_click_and_refuses_its_modal_with_interaction_expired():
    """handle / gives Late for a late click, and refuses its modal with interaction_expired"""
    refused = yield from Deferred[ChatError].make()
    opened = ci.modal("m", title="M", fields={}).open()
    handler = handler_with(
        click=fx.sleep("5 seconds").as_(opened),
        refused=lambda error: refused.succeed(error).as_void(),
    )
    fiber = yield from (
        ci.handle(clicked("a"), DEADLINE).pipe(fx.provide_service(ci.Handler, handler)).fork()
    )
    yield from testing.adjust("3 seconds")
    reply = yield from fiber.join()
    assert isinstance(reply, ci.Late)
    # The click's handler is still running, and its modal can no longer open.
    yield from testing.adjust("2 seconds")
    error = yield from refused.wait()
    assert error.op == "openModal"
    assert error.platform == "test"
    assert error.reason._tag == "NotFound"  # pyright: ignore[reportPrivateUsage]
    assert error.reason.detail == INTERACTION_EXPIRED


@testing.effect
def test_gives_late_at_the_deadline_without_waiting_for_a_late_submits_cleanup():
    """handle / gives Late at the deadline without waiting for a late submit's cleanup"""
    cleaned = yield from Deferred[None].make()
    handler = handler_with(
        submit=fx.never.on_interrupt(fx.sleep("5 seconds").and_then(cleaned.succeed(None)))
    )
    fiber = yield from (
        ci.handle(submitted("m", {}), DEADLINE).pipe(fx.provide_service(ci.Handler, handler)).fork()
    )
    yield from testing.adjust("3 seconds")
    exit = fiber.poll_unsafe()
    assert isinstance(exit, Success)
    assert isinstance(exit.value, ci.Late)
    # The interrupt was requested, and the cleanup still runs to its end.
    assert not (yield from cleaned.is_done())
    yield from testing.adjust("5 seconds")
    yield from cleaned.wait()


# --- ChatTest.interact ---------------------------------------------------------------


@testing.effect
def test_follows_up_a_deferral_once_inside_follow_up_age():
    """ChatTest.interact / follows up a deferral once, inside followUpAge"""

    @fx.gen
    def program() -> Gen[None]:
        test = yield from ChatTest()
        chat = yield from Chat()
        channel = yield from test.make_thread()
        handler = handler_with(command=ci.defer)

        @fx.gen
        def interact() -> Gen[ci.Defer]:
            command = yield from test.command(channel, "summarize")
            reply = yield from test.interact(command).pipe(fx.provide_service(ci.Handler, handler))
            assert isinstance(reply, ci.Defer)
            return reply

        first = yield from interact
        yield from chat.follow_up(first, markdown="Done")
        twice = yield from chat.follow_up(first, markdown="Again").flip()
        assert twice.reason.detail == INTERACTION_EXPIRED
        second = yield from interact
        yield from testing.adjust("15 minutes")
        expired = yield from chat.follow_up(second, markdown="Late").flip()
        assert expired.reason._tag == "NotFound"  # pyright: ignore[reportPrivateUsage]
        assert expired.reason.detail == INTERACTION_EXPIRED

    return program.pipe(fx.provide(chat_test.layer()))


@testing.effect
def test_refuses_a_private_answer_without_ephemeral_and_sends_nothing():
    """ChatTest.interact / refuses a private answer without ephemeral, and sends nothing"""

    @fx.gen
    def program() -> Gen[None]:
        test = yield from ChatTest()
        channel = yield from test.make_thread()
        refused: list[ChatError] = []

        def answer(command: ci.CommandInvoked) -> ci.CommandReply:
            return ci.defer(command) if command.text == "defer" else ci.respond(markdown="Secret")

        handler = handler_with(
            command=answer, refused=lambda error: fx.sync(lambda: refused.append(error))
        )
        for text in ("respond", "defer"):
            command = yield from test.command(channel, "secret", text=text)
            yield from test.interact(command).pipe(fx.provide_service(ci.Handler, handler))
        assert [
            error.reason.capability if isinstance(error.reason, Unsupported) else None
            for error in refused
        ] == ["ephemeral", "ephemeral"]
        assert [(call.op, call.outcome) for call in (yield from test.calls)] == [
            ("respond", "Unsupported")
        ]

    return program.pipe(
        fx.provide(chat_test.layer(capabilities=[c for c in CAPABILITIES if c != "ephemeral"]))
    )
