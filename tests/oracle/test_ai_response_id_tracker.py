"""Ports of Effect's ``test/ai/ResponseIdTracker.test.ts``,
``Model.test.ts`` and ``Tokenizer.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
``Option.none()`` is ``None``.
"""

from __future__ import annotations

import pyfect as fx
from pyfect import layer as L
from pyfect import testing
from pyfect.ai import model as M
from pyfect.ai import prompt as P
from pyfect.ai import response_id_tracker as tracker
from pyfect.ai import tokenizer as Tk


def system(text: str) -> P.SystemMessage:
    return P.SystemMessage(content=text)


def user(text: str) -> P.UserMessage:
    return P.UserMessage(content=[P.TextPart(text=text)])


def assistant(text: str) -> P.AssistantMessage:
    return P.AssistantMessage(content=[P.TextPart(text=text)])


def assistant_tool_call(id: str) -> P.AssistantMessage:
    return P.AssistantMessage(
        content=[P.ToolCallPart(id=id, name="test_tool", params={"query": "query"})]
    )


def tool_result(id: str) -> P.ToolMessage:
    return P.ToolMessage(
        content=[P.ToolResultPart(id=id, name="test_tool", result={"ok": True}, is_failure=False)]
    )


def prompt(*messages: P.Message) -> P.Prompt:
    return P.from_messages(messages)


def assert_prepared(
    prepared: tracker.PrepareResult | None, previous_response_id: str, expected: P.Prompt
) -> None:
    assert prepared is not None
    assert prepared.previous_response_id == previous_response_id
    assert prepared.prompt == expected


@testing.effect
def test_fresh_tracker():
    """ResponseIdTracker / returns None for a fresh tracker"""
    t = yield from tracker.make
    assert t.prepare_unsafe(prompt(user("msg1"))) is None


@testing.effect
def test_prepares_new_user_message():
    """ResponseIdTracker / prepares only the new user message after a tracked first turn"""
    t = yield from tracker.make
    msg1, asst, msg2 = user("msg1"), assistant("done"), user("msg2")
    t.mark_parts([msg1], "resp_123")
    assert_prepared(t.prepare_unsafe(prompt(msg1, asst, msg2)), "resp_123", prompt(msg2))


@testing.effect
def test_shares_state_through_service():
    """ResponseIdTracker / shares tracker state through its Context service layer"""
    t = yield from tracker.make
    shared = yield from tracker.ResponseIdTracker().pipe(
        fx.provide_service(tracker.ResponseIdTracker, t)
    )
    msg1, msg1_new, asst, msg2 = user("msg1"), user("msg1-new"), assistant("done"), user("msg2")
    t.mark_parts([msg1], "resp_123")
    shared.clear_unsafe()
    shared.mark_parts([msg1_new], "resp_456")
    assert_prepared(t.prepare_unsafe(prompt(msg1_new, asst, msg2)), "resp_456", prompt(msg2))


@testing.effect
def test_keeps_latest_response_id():
    """ResponseIdTracker / keeps latest response id when markParts is called twice"""
    t = yield from tracker.make
    msg1, asst, msg2 = user("msg1"), assistant("done"), user("msg2")
    t.mark_parts([msg1], "resp_1")
    t.mark_parts([msg1], "resp_2")
    assert_prepared(t.prepare_unsafe(prompt(msg1, asst, msg2)), "resp_2", prompt(msg2))


@testing.effect
def test_none_after_clear():
    """ResponseIdTracker / returns None after clear"""
    t = yield from tracker.make
    msg1, asst, msg2 = user("msg1"), assistant("done"), user("msg2")
    t.mark_parts([msg1], "resp_123")
    t.clear_unsafe()
    assert t.prepare_unsafe(prompt(msg1, asst, msg2)) is None


@testing.effect
def test_none_after_explicit_clear():
    """ResponseIdTracker / returns None after explicit clear"""
    t = yield from tracker.make
    sys, user1, asst1, user2 = system("sys"), user("user1"), assistant("assistant1"), user("user2")
    t.mark_parts([sys, user1], "resp_1")
    t.clear_unsafe()
    assert t.prepare_unsafe(prompt(sys, user1, asst1, user2)) is None


@testing.effect
def test_recovers_after_clear():
    """ResponseIdTracker / recovers after clear with new marks"""
    t = yield from tracker.make
    msg1, msg1_new, asst, msg2 = user("msg1"), user("msg1-new"), assistant("done"), user("msg2")
    t.mark_parts([msg1], "resp_123")
    t.clear_unsafe()
    t.mark_parts([msg1_new], "resp_456")
    assert_prepared(t.prepare_unsafe(prompt(msg1_new, asst, msg2)), "resp_456", prompt(msg2))


@testing.effect
def test_concurrent_mark_and_clear():
    """ResponseIdTracker / remains usable after concurrent markParts and clear"""
    t = yield from tracker.make
    race = user("race")

    def marks() -> fx.Effect[None]:
        return fx.for_each(
            range(200),
            lambda _: fx.sync(lambda: t.mark_parts([race], "resp_race")).and_then(fx.yield_now()),
        ).as_(None)

    def clears() -> fx.Effect[None]:
        return fx.for_each(
            range(200), lambda _: fx.sync(t.clear_unsafe).and_then(fx.yield_now())
        ).as_(None)

    yield from fx.for_each([marks(), clears()], lambda e: e, concurrency="unbounded")
    msg1, asst, msg2 = user("msg1"), assistant("done"), user("msg2")
    t.mark_parts([msg1], "resp_final")
    assert_prepared(t.prepare_unsafe(prompt(msg1, asst, msg2)), "resp_final", prompt(msg2))


@testing.effect
def test_first_turn_system_and_user():
    """ResponseIdTracker / returns None for first turn with system and user messages"""
    t = yield from tracker.make
    assert t.prepare_unsafe(prompt(system("sys"), user("user1"))) is None


@testing.effect
def test_no_assistant_message():
    """ResponseIdTracker / returns None when tracked prompt has no assistant message"""
    t = yield from tracker.make
    sys, user1 = system("sys"), user("user1")
    t.mark_parts([sys, user1], "resp_1")
    assert t.prepare_unsafe(prompt(sys, user1)) is None


@testing.effect
def test_user_follow_up():
    """ResponseIdTracker / returns incremental user follow-up after assistant"""
    t = yield from tracker.make
    sys, user1, asst1, user2 = system("sys"), user("user1"), assistant("assistant1"), user("user2")
    t.mark_parts([sys, user1], "resp_1")
    assert_prepared(t.prepare_unsafe(prompt(sys, user1, asst1, user2)), "resp_1", prompt(user2))


@testing.effect
def test_tool_results_after_tool_call():
    """ResponseIdTracker / returns incremental tool results after assistant tool call"""
    t = yield from tracker.make
    sys, user1 = system("sys"), user("user1")
    asst1, tool1 = assistant_tool_call("call_1"), tool_result("call_1")
    t.mark_parts([sys, user1], "resp_1")
    assert_prepared(t.prepare_unsafe(prompt(sys, user1, asst1, tool1)), "resp_1", prompt(tool1))


@testing.effect
def test_tool_results_and_user_message():
    """ResponseIdTracker / returns incremental tool results plus user message in multi-step flow"""
    t = yield from tracker.make
    sys, user1, user2 = system("sys"), user("user1"), user("user2")
    asst1, tool1 = assistant_tool_call("call_1"), tool_result("call_1")
    t.mark_parts([sys, user1], "resp_1")
    assert_prepared(
        t.prepare_unsafe(prompt(sys, user1, asst1, tool1, user2)), "resp_1", prompt(tool1, user2)
    )


@testing.effect
def test_nothing_after_assistant():
    """ResponseIdTracker / returns None when no new messages follow assistant"""
    t = yield from tracker.make
    sys, user1, asst1 = system("sys"), user("user1"), assistant("assistant1")
    t.mark_parts([sys, user1], "resp_1")
    assert t.prepare_unsafe(prompt(sys, user1, asst1)) is None


@testing.effect
def test_nothing_after_last_assistant():
    """ResponseIdTracker / returns None in multi-turn prompt with no messages after last assistant"""  # noqa: E501
    t = yield from tracker.make
    sys, user1, asst1 = system("sys"), user("user1"), assistant("assistant1")
    user2, asst2 = user("user2"), assistant("assistant2")
    t.mark_parts([sys, user1, asst1, user2], "resp_2")
    assert t.prepare_unsafe(prompt(sys, user1, asst1, user2, asst2)) is None


@testing.effect
def test_empty_prompt():
    """ResponseIdTracker / returns None for empty prompt"""
    t = yield from tracker.make
    assert t.prepare_unsafe(prompt()) is None


@testing.effect
def test_none_when_system_prompt_changes():
    """ResponseIdTracker / returns None when system prompt object changes"""
    t = yield from tracker.make
    sys, user1, asst1, user2 = system("sys"), user("user1"), assistant("assistant1"), user("user2")
    t.mark_parts([sys, user1], "resp_1")
    assert t.prepare_unsafe(prompt(system("sys-new"), user1, asst1, user2)) is None


@testing.effect
def test_none_when_user_message_changes():
    """ResponseIdTracker / returns None when user message object changes"""
    t = yield from tracker.make
    sys, user1, asst1, user2 = system("sys"), user("user1"), assistant("assistant1"), user("user2")
    t.mark_parts([sys, user1], "resp_1")
    assert t.prepare_unsafe(prompt(sys, user("user1-edited"), asst1, user2)) is None


@testing.effect
def test_none_when_multiple_prefix_messages_diverge():
    """ResponseIdTracker / returns None when multiple prefix messages diverge"""
    t = yield from tracker.make
    sys, user1, asst1, user2 = system("sys"), user("user1"), assistant("assistant1"), user("user2")
    t.mark_parts([sys, user1], "resp_1")
    changed = prompt(system("sys-new"), user("user1-edited"), asst1, user2)
    assert t.prepare_unsafe(changed) is None


@testing.effect
def test_none_for_identity_different_prefix_message():
    """ResponseIdTracker / returns None for structurally-equal but identity-different prefix message"""  # noqa: E501
    t = yield from tracker.make
    msg1, asst1, msg2 = user("msg1"), assistant("assistant1"), user("msg2")
    t.mark_parts([msg1], "resp_1")
    assert t.prepare_unsafe(prompt(user("msg1"), asst1, msg2)) is None


@testing.effect
def test_recovers_after_divergence():
    """ResponseIdTracker / clears stale state after divergence and recovers when the new prefix is re-marked"""  # noqa: E501
    t = yield from tracker.make
    sys, user1, sys_new = system("sys"), user("user1"), system("sys-new")
    asst1, user2 = assistant("assistant1"), user("user2")
    t.mark_parts([sys, user1], "resp_1")
    assert t.prepare_unsafe(prompt(sys_new, user1, asst1, user2)) is None
    t.mark_parts([sys_new, user1], "resp_2")
    assert_prepared(t.prepare_unsafe(prompt(sys_new, user1, asst1, user2)), "resp_2", prompt(user2))


@testing.effect
def test_two_turn_lifecycle():
    """ResponseIdTracker / supports full lifecycle across two turns"""
    t = yield from tracker.make
    sys, user1, asst1, user2 = system("sys"), user("user1"), assistant("assistant1"), user("user2")
    asst2, user3 = assistant("assistant2"), user("user3")
    t.mark_parts([sys, user1], "resp_1")
    assert_prepared(t.prepare_unsafe(prompt(sys, user1, asst1, user2)), "resp_1", prompt(user2))
    t.mark_parts([sys, user1, asst1, user2], "resp_2")
    assert_prepared(
        t.prepare_unsafe(prompt(sys, user1, asst1, user2, asst2, user3)), "resp_2", prompt(user3)
    )


@testing.effect
def test_two_conversations():
    """ResponseIdTracker / isolates two conversations on the same tracker"""
    t = yield from tracker.make
    sys_a, user_a1, asst_a1, user_a2 = (
        system("sysA"),
        user("userA1"),
        assistant("a"),
        user("userA2"),
    )
    sys_b, user_b1, asst_b1, user_b2 = (
        system("sysB"),
        user("userB1"),
        assistant("b"),
        user("userB2"),
    )
    t.mark_parts([sys_a, user_a1], "resp_A1")
    t.mark_parts([sys_b, user_b1], "resp_B1")
    assert_prepared(
        t.prepare_unsafe(prompt(sys_a, user_a1, asst_a1, user_a2)), "resp_A1", prompt(user_a2)
    )
    assert_prepared(
        t.prepare_unsafe(prompt(sys_b, user_b1, asst_b1, user_b2)), "resp_B1", prompt(user_b2)
    )


@testing.effect
def test_no_leak_without_assistant_turns():
    """ResponseIdTracker / does not leak tracked state across conversations without assistant turns"""  # noqa: E501
    t = yield from tracker.make
    sys_a, user_a1, asst_a1, user_a2 = (
        system("sysA"),
        user("userA1"),
        assistant("a"),
        user("userA2"),
    )
    sys_b, user_b1 = system("sysB"), user("userB1")
    t.mark_parts([sys_a, user_a1], "resp_A1")
    t.mark_parts([sys_b, user_b1], "resp_B1")
    assert_prepared(
        t.prepare_unsafe(prompt(sys_a, user_a1, asst_a1, user_a2)), "resp_A1", prompt(user_a2)
    )
    assert t.prepare_unsafe(prompt(sys_b, user_b1)) is None


@testing.effect
def test_model_provides_metadata():
    """Model / provides metadata alongside the wrapped layer for the duration of the scope"""

    names = yield from (
        M.ProviderName()
        .zip(M.ModelName())
        .pipe(fx.provide(M.make("openai", "gpt-5", L.empty).layer))
    )
    assert names == ("openai", "gpt-5")


@testing.effect
def test_tokenizer_truncate_costs_between_messages():
    """Tokenizer / truncate accounts for costs between messages"""
    tokenizer = Tk.make(tokenize=lambda p: fx.succeed(list(range(max(0, len(p.content) * 2 - 1)))))
    input = P.make([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    output = yield from tokenizer.truncate(input, 2)
    assert output.content == (input.content[1],)
    tokens = yield from tokenizer.tokenize(output)
    assert len(tokens) <= 2
