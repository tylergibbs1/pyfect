"""``Chat`` (Effect's ``effect/ai/Chat``): a conversation that keeps its
history. Each call sends the history plus the new prompt to the
``LanguageModel`` and appends the prompt and the response to the history;
calls on one chat run one at a time::

    chat = yield from chat_.empty
    yield from chat.generate_text("Hi, I'm Ada")
    reply = yield from chat.generate_text("What is my name?")

``export`` / ``export_json`` and ``from_export`` / ``from_json`` save and
restore a history. ``Persistence`` (``layer_persisted``) keeps chats in a
``BackingPersistence`` store by id, saving after every call and tagging
each new message with a message id under ``PERSISTENCE_KEY``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, LiteralString, Never, cast, overload

import pyfect as fx
from pyfect import schema as S
from pyfect._concurrency import Concurrency
from pyfect._core import Effect
from pyfect.ai import _partial_turns as _partial
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import toolkit as K
from pyfect.ai._stream_resolution import resolvable_tool, resolve_calls
from pyfect.ai.ai_error import AiError, InvalidOutputError
from pyfect.ai.id_generator import IdGenerator, default_id_generator
from pyfect.ai.id_generator import Service as IdService
from pyfect.channel import acquire_use_release
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.effect import sync
from pyfect.exit import Exit, Success
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.option import Option
from pyfect.persistence import PersistenceError
from pyfect.persistence.persistence import BackingPersistence, BackingPersistenceStore
from pyfect.ref import Ref
from pyfect.schema import SchemaError
from pyfect.scope import Scope
from pyfect.semaphore import Semaphore
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC
from pyfect.stream._stream import from_channel, to_channel

type _ToolkitInput[NN: LiteralString, RP, EE, RR] = (
    K.WithHandler[NN, RP, EE, RR] | Effect[K.WithHandler[NN, RP, EE, RR], EE, RR]
)

_PROMPT_JSON = S.from_json_string(P.Prompt.__codec__())
_encode = S.encode_unknown_effect(P.Prompt.__codec__())
_encode_json = S.encode_unknown_effect(_PROMPT_JSON)
_decode = S.decode_unknown_effect(P.Prompt.__codec__())
_decode_json = S.decode_unknown_effect(_PROMPT_JSON)


def _invalid_output(method: str) -> Callable[[SchemaError], AiError]:
    return lambda error: AiError(
        module="Chat", method=method, reason=InvalidOutputError.from_schema_error(error)
    )


class Service:
    """A chat. ``history`` is the conversation so far; set it to rewrite it."""

    def __init__(
        self,
        history: Ref[P.Prompt],
        after_call: Callable[[P.Prompt], Effect[None]] | None = None,
    ) -> None:
        self.history = history
        self._lock = Semaphore(1)
        # Run after each call with the history from before it (Persisted's save).
        self._after_call = after_call

    @property
    def export(self) -> Effect[object, AiError]:
        """The history in its JSON wire form."""
        encoded = self.history.get().flat_map(_encode)
        return encoded.map_error(_invalid_output("export")).with_span("Chat.export")

    @property
    def export_json(self) -> Effect[str, AiError]:
        """The history as JSON text."""
        encoded = self.history.get().flat_map(lambda h: _encode_json(h).map(str))
        return encoded.map_error(_invalid_output("exportJson")).with_span("Chat.exportJson")

    def _call[A: lm.GenerateTextResponse[Any, Any], E, RR](
        self, prompt: P.RawInput, tools: _TurnTools, call: _Call[A, E, RR]
    ) -> Effect[A, E, RR]:
        """``call`` with the history plus ``prompt``; the history then gains
        the response's parts."""

        def run(history: P.Prompt) -> Effect[A, E, RR]:
            full = history.concat(prompt)
            return call(full, tools.toolkit, None).flat_map(
                lambda response: self.history.set(full.concat(_reply(response))).as_(response)
            )

        locked = self._lock.with_permits(self.history.get().flat_map(run))
        return self._after(locked)

    def _after[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        after = self._after_call
        if after is None:
            return eff
        return self.history.get().flat_map(lambda before: eff.ensuring(after(before)))

    @overload
    def generate_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
    ) -> Effect[lm.GenerateTextResponse[str, Never], AiError, lm.LanguageModel]: ...
    @overload
    def generate_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
    ) -> Effect[lm.GenerateTextResponse[Never, Never], AiError, lm.LanguageModel]: ...
    @overload
    def generate_text[NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
    ) -> Effect[lm.GenerateTextResponse[str, RP], AiError | EE, lm.LanguageModel | RR]: ...
    @overload
    def generate_text[NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
    ) -> Effect[lm.GenerateTextResponse[NN, RP], AiError | EE, lm.LanguageModel | RR]: ...
    def generate_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: Any = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: lm.ToolCallValidation = "strict",
    ) -> Effect[Any, Any, Any]:
        """``language_model.generate_text`` on the history plus ``prompt``."""
        return self._call(
            prompt,
            _TurnTools(toolkit, not disable_tool_call_resolution),
            lambda full, kit, received: _model().flat_map(
                lambda model: model._generate_text(  # pyright: ignore[reportPrivateUsage]
                    full,
                    received,
                    toolkit=kit,
                    tool_choice=tool_choice,
                    concurrency=concurrency,
                    disable_tool_call_resolution=disable_tool_call_resolution,
                    tool_call_validation=tool_call_validation,
                )
            ),
        ).with_span("Chat.generateText")

    @overload
    def generate_object[A](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
        allow_empty: Literal[False] = False,
    ) -> Effect[lm.GenerateObjectResponse[str, Never, A], AiError, lm.LanguageModel]: ...
    @overload
    def generate_object[A](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
        allow_empty: Literal[False] = False,
    ) -> Effect[lm.GenerateObjectResponse[Never, Never, A], AiError, lm.LanguageModel]: ...
    @overload
    def generate_object[A, NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
        allow_empty: Literal[False] = False,
    ) -> Effect[lm.GenerateObjectResponse[str, RP, A], AiError | EE, lm.LanguageModel | RR]: ...
    @overload
    def generate_object[A, NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
        allow_empty: Literal[False] = False,
    ) -> Effect[lm.GenerateObjectResponse[NN, RP, A], AiError | EE, lm.LanguageModel | RR]: ...
    @overload
    def generate_object[A](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
        allow_empty: Literal[True],
    ) -> Effect[lm.GenerateObjectResponse[str, Never, Option[A]], AiError, lm.LanguageModel]: ...
    @overload
    def generate_object[A](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
        allow_empty: Literal[True],
    ) -> Effect[lm.GenerateObjectResponse[Never, Never, Option[A]], AiError, lm.LanguageModel]: ...
    @overload
    def generate_object[A, NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
        allow_empty: Literal[True],
    ) -> Effect[
        lm.GenerateObjectResponse[str, RP, Option[A]], AiError | EE, lm.LanguageModel | RR
    ]: ...
    @overload
    def generate_object[A, NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        schema: S.Codec[A, Any, Any, Any],
        object_name: str | None = None,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
        allow_empty: Literal[True],
    ) -> Effect[
        lm.GenerateObjectResponse[NN, RP, Option[A]], AiError | EE, lm.LanguageModel | RR
    ]: ...
    def generate_object(
        self,
        prompt: P.RawInput,
        *,
        schema: S.Top,
        object_name: str | None = None,
        toolkit: Any = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: lm.ToolCallValidation = "strict",
        allow_empty: bool = False,
    ) -> Effect[Any, Any, Any]:
        """``language_model.generate_object`` on the history plus ``prompt``."""
        call = self._call(
            prompt,
            _TurnTools(toolkit, not disable_tool_call_resolution),
            lambda full, kit, received: _model().flat_map(
                lambda model: model._generate_object(  # pyright: ignore[reportPrivateUsage]
                    full,
                    received,
                    schema=schema,
                    object_name=object_name,
                    toolkit=kit,
                    tool_choice=tool_choice,
                    concurrency=concurrency,
                    disable_tool_call_resolution=disable_tool_call_resolution,
                    tool_call_validation=tool_call_validation,
                    allow_empty=allow_empty,
                )
            ),
        )
        name = lm.get_object_name(object_name, schema)
        return call.with_span("Chat.generateObject", attributes={"effect.ai.object_name": name})

    @overload
    def stream_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
        max_steps: int = 1,
    ) -> Stream[R.StreamPart[str, Never], AiError, lm.LanguageModel]: ...
    @overload
    def stream_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: None = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
        max_steps: int = 1,
    ) -> Stream[R.StreamPart[Never, Never], AiError, lm.LanguageModel]: ...
    @overload
    def stream_text[NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: Literal[True],
        tool_call_validation: Literal["deferred"],
        max_steps: int = 1,
    ) -> Stream[R.StreamPart[str, RP], AiError | EE, lm.LanguageModel | RR]: ...
    @overload
    def stream_text[NN: LiteralString, RP, EE, RR](
        self,
        prompt: P.RawInput,
        *,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: Literal["strict"] = "strict",
        max_steps: int = 1,
    ) -> Stream[R.StreamPart[NN, RP], AiError | EE, lm.LanguageModel | RR]: ...
    def stream_text(
        self,
        prompt: P.RawInput,
        *,
        toolkit: Any = None,
        tool_choice: lm.ToolChoice = "auto",
        concurrency: Concurrency = "unbounded",
        disable_tool_call_resolution: bool = False,
        tool_call_validation: lm.ToolCallValidation = "strict",
        max_steps: int = 1,
    ) -> Stream[Any, Any, Any]:
        """``language_model.stream_text`` on the history plus ``prompt``.
        The history gains the parts streamed, also when the stream is cut
        short.

        The model is called once by default. With ``max_steps``, the chat calls it again
        with the updated history while each round ends in tool calls that were all
        resolved, for at most ``max_steps`` rounds. The loop stops at a round that needs
        no tools, an incomplete finish, or a tool call left unanswered, such as a
        client-executed tool call or an approval request. The stream carries every
        round's parts, each round ending with its own ``finish`` part, and the history
        records each round in order."""

        def stream_round(prompt: P.Prompt, kit: Any) -> Effect[Stream[Any, Any, Any], Never, Any]:
            return _model().map(
                lambda model: model.stream_text(
                    prompt,
                    toolkit=kit,
                    tool_choice=tool_choice,
                    concurrency=concurrency,
                    disable_tool_call_resolution=disable_tool_call_resolution,
                    tool_call_validation=tool_call_validation,
                )
            )

        tools = _TurnTools(toolkit, not disable_tool_call_resolution)
        stream = self._stream_turn(prompt, tools, stream_round, max_steps)
        stream = stream.with_span("Chat.streamText")
        after = self._after_call
        if after is None:
            return stream
        return StreamC.unwrap(self.history.get().map(lambda before: stream.ensuring(after(before))))

    def _stream_turn(
        self, prompt: P.RawInput, tools: _TurnTools, stream_round: _StreamRound, max_steps: int
    ) -> Stream[Any, Any, Any]:
        return self._stream_rounds(prompt, tools.toolkit, stream_round, max_steps, list)

    def _stream_rounds(
        self,
        prompt: P.RawInput,
        toolkit: Any,
        stream_round: _StreamRound,
        max_steps: int,
        close: Callable[[list[Any]], list[Any]],
    ) -> Stream[Any, Any, Any]:
        """The rounds of a ``stream_text`` call; the history gains every round, the last
        one's parts so far through ``close``."""

        def start() -> Stream[Any, Any, Any]:
            loop = _StepLoop(lambda prompt: stream_round(prompt, toolkit), max_steps)

            def begin(history: P.Prompt) -> None:
                loop.completed = history.concat(prompt)

            def use(_: None) -> Any:
                return to_channel(loop.run_round(1))

            def release(_: None, __: Exit[Any, Any]) -> Effect[object]:
                done = loop.completed.concat(P.from_response_parts(close(loop.parts)))
                return self.history.set(done).and_then(self._lock.release(1))

            acquire = self._lock.take(1).and_then(self.history.get()).map(begin)
            # Effect's Channel.acquireUseRelease: the history is set when the
            # model's stream ends, before any finalizer added outside (the save).
            return from_channel(acquire_use_release(acquire, use, release))

        return StreamC.unwrap(fx.sync(start))


@dataclass(frozen=True)
class _TurnTools:
    """A call's ``toolkit`` as given, and whether the chat runs its tool calls."""

    toolkit: Any
    resolves: bool


type _Call[A, E, RR] = Callable[[P.Prompt, Any, list[Any] | None], Effect[A, E, RR]]
"""A model call on the full prompt, with the toolkit and the list that receives each part
once it is decided (``None``: nothing is told)."""

type _StreamRound = Callable[[P.Prompt, Any], Effect[Stream[Any, Any, Any], Never, Any]]


def _reply(response: lm.GenerateTextResponse[Any, Any]) -> P.Prompt:
    return P.from_response_parts(cast("list[R.AnyPart]", response.content))


class _StepLoop:
    """The rounds of one ``stream_text`` call: the prompt including every completed
    round, and the parts of the round in progress, so an interrupted round keeps its
    partial output. A state object, so the rounds do not reach each other through
    closure cells."""

    def __init__(
        self,
        stream_round: Callable[[P.Prompt], Effect[Stream[Any, Any, Any], Never, Any]],
        max_steps: int,
    ) -> None:
        self.stream_round = stream_round
        self.max_steps = max_steps
        self.completed: P.Prompt = P.empty
        self.parts: list[Any] = []

    def collect(self, chunk: tuple[Any, ...]) -> tuple[Any, ...]:
        self.parts.extend(chunk)
        return chunk

    def run_round(self, step: int) -> Stream[Any, Any, Any]:
        streamed = StreamC.unwrap(self.stream_round(self.completed))
        return streamed.map_array(self.collect).concat(
            StreamC.suspend(lambda: self.next_round(step))
        )

    def next_round(self, step: int) -> Stream[Any, Any, Any]:
        round = list(self.parts)
        self.completed = self.completed.concat(P.from_response_parts(round))
        self.parts = []
        if step < self.max_steps and _should_continue(round):
            return self.run_round(step + 1)
        return StreamC.empty


def _should_continue(round: list[R.AnyPart]) -> bool:
    """Whether a round continues the step loop: it ended in tool calls that all have a
    final result. A client-executed tool call or an approval request has none, and an
    incomplete finish ends the loop."""
    finish = next((part for part in round if isinstance(part, R.FinishPart)), None)
    if finish is None or finish.reason != "tool-calls":
        return False
    unanswered: set[str] = set()
    for part in round:
        if isinstance(part, R.ToolCallPart):
            unanswered.add(part.id)
        elif isinstance(part, (R.ToolResultSuccess, R.ToolResultFailure)) and not part.preliminary:
            unanswered.discard(part.id)
    return not unanswered and any(isinstance(part, R.ToolCallPart) for part in round)


def _model() -> Effect[lm.Service, Never, lm.LanguageModel]:
    return lm.LanguageModel()


class Chat(Tag[Service], key="effect/ai/Chat"):
    """The chat of the current context."""


empty: Effect[Service] = sync(lambda: Service(Ref(P.empty)))
"""A chat with no history."""


def from_prompt(prompt: P.RawInput) -> Effect[Service]:
    """A chat whose history is ``prompt``."""
    return fx.sync(lambda: Service(Ref(P.make(prompt))))


def from_export(data: object) -> Effect[Service, SchemaError]:
    """A chat from ``export``'s wire form."""
    return _decode(data).flat_map(from_prompt)


def from_json(data: str) -> Effect[Service, SchemaError]:
    """A chat from ``export_json``'s text."""
    return _decode_json(data).flat_map(from_prompt)


# --- interrupt-safe turns -------------------------------------------------------------


class InterruptSafe(Service):
    """``chat`` (its history, its lock and its saves) with turns that commit when cut
    short. Effect's chat records a turn only when the call succeeds; this one also
    records an interrupted or failed one, as a history every provider takes: the prompt,
    the model's output received, and each tool call with its result, or with an
    ``execution-interrupted`` result when it did not finish. ``resume`` runs those again.
    A finished turn is recorded as Effect's chat records it."""

    def __init__(self, chat: Service) -> None:
        super().__init__(chat.history, chat._after_call)
        self._lock = chat._lock
        self.chat = chat
        """The chat this one commits to (a ``Persisted`` one keeps its ``save``)."""

    def _call[A: lm.GenerateTextResponse[Any, Any], E, RR](
        self, prompt: P.RawInput, tools: _TurnTools, call: _Call[A, E, RR]
    ) -> Effect[A, E, RR]:
        def run(history: P.Prompt) -> Effect[A, E, RR]:
            turn = _Turn(history.concat(prompt), tools.resolves)
            started = _optional_kit(tools.toolkit).flat_map(
                lambda kit: call(turn.prompt, turn.uses(kit), turn.received)
            )
            return started.on_exit(lambda exit: self.history.set(turn.committed(exit)))

        locked = self._lock.with_permits(self.history.get().flat_map(run))
        return self._after(locked)

    def _stream_turn(
        self, prompt: P.RawInput, tools: _TurnTools, stream_round: _StreamRound, max_steps: int
    ) -> Stream[Any, Any, Any]:
        def rounds(kit: K.WithHandler[Any, Any, Any, Any] | None) -> Stream[Any, Any, Any]:
            runs = _runs_handler(kit, tools.resolves)

            def close(parts: list[Any]) -> list[Any]:
                return _partial.closed(parts, runs)

            return self._stream_rounds(prompt, kit, stream_round, max_steps, close)

        return StreamC.unwrap(_optional_kit(tools.toolkit).map(rounds))

    def resume[NN: LiteralString, RP, EE, RR](
        self,
        *,
        toolkit: _ToolkitInput[NN, RP, EE, RR],
        concurrency: Concurrency = "unbounded",
    ) -> Effect[tuple[RP | R.ToolApprovalRequestPart, ...], AiError | EE, RR]:
        """Run again the tool calls the last turn left without a result, with
        ``toolkit``, and put their results in the history in place of the
        ``execution-interrupted`` ones: the results, in the order they finished. With a
        toolkit behind ``tool_ledger.guard``, a call whose handler ran before is answered
        from the ledger. A call that needs approval gets its approval request instead.
        Interrupted again, the history keeps what finished."""

        def run(history: P.Prompt) -> Effect[tuple[Any, ...], Any, Any]:
            calls = _partial.unfinished(history)
            if not calls:
                return fx.succeed(())
            done: list[Any] = []

            def received(part: Any) -> Any:
                done.append(part)
                return part

            def resolve(kit: K.WithHandler[Any, Any, Any, Any]) -> Effect[Any, Any, Any]:
                encoded = [
                    {"type": "tool-call", "id": c.id, "name": c.name, "params": c.params}
                    for c in calls
                ]
                resolved = resolve_calls(kit, encoded, history.content, concurrency)
                final = resolved.filter(
                    lambda r: isinstance(r, R.ToolApprovalRequestPart) or not r.preliminary
                )
                return final.map(received).run_drain()

            ran = _kit(toolkit).flat_map(resolve).pipe(_with_id_generator)
            committed = ran.on_exit(lambda _: self.history.set(_partial.resumed(history, done)))
            return committed.map(lambda _: tuple(done))

        locked = self._lock.with_permits(self.history.get().flat_map(run))
        return self._after(locked).with_span("Chat.resume")


def interrupt_safe(chat: Service) -> InterruptSafe:
    """``chat``, with turns that commit when interrupted or failed (``InterruptSafe``)."""
    return InterruptSafe(chat)


class _Turn:
    """One interrupt-safe call: the prompt sent, the toolkit and the parts received."""

    def __init__(self, prompt: P.Prompt, resolves: bool) -> None:
        self.prompt = prompt
        self.resolves = resolves
        self.kit: K.WithHandler[Any, Any, Any, Any] | None = None
        self.received: list[Any] = []

    def uses(
        self, kit: K.WithHandler[Any, Any, Any, Any] | None
    ) -> K.WithHandler[Any, Any, Any, Any] | None:
        self.kit = kit
        return kit

    def committed(self, exit: Exit[lm.GenerateTextResponse[Any, Any], Any]) -> P.Prompt:
        """The history after the call: the response's parts as Effect's chat adds them,
        or the parts received, closed."""
        if isinstance(exit, Success):
            return self.prompt.concat(_reply(exit.value))
        parts = _partial.closed(self.received, _runs_handler(self.kit, self.resolves))
        return self.prompt.concat(P.from_response_parts(parts))


def _optional_kit(toolkit: object) -> Effect[K.WithHandler[Any, Any, Any, Any] | None, Any, Any]:
    return fx.succeed(None) if toolkit is None else _kit(toolkit)


def _kit(toolkit: object) -> Effect[K.WithHandler[Any, Any, Any, Any], Any, Any]:
    if isinstance(toolkit, Effect):
        return cast("Effect[K.WithHandler[Any, Any, Any, Any], Any, Any]", toolkit)
    return fx.succeed(cast("K.WithHandler[Any, Any, Any, Any]", toolkit))


def _runs_handler(
    kit: K.WithHandler[Any, Any, Any, Any] | None, resolves: bool
) -> Callable[[str], bool]:
    """Whether the chat runs a handler for a call to the tool ``name``."""
    return lambda name: resolves and kit is not None and resolvable_tool(kit, name) is not None


def _with_id_generator[A, E, R](eff: Effect[A, E, R]) -> Effect[A, E, R]:
    """``eff`` with an ``IdGenerator`` (for approval requests): the one in context, else
    the default one."""
    return fx.service_option(IdGenerator).flat_map(
        lambda found: eff.pipe(
            fx.provide_service(
                IdGenerator, found.value if found is not None else default_id_generator
            )
        )
    )


# --- persistence ----------------------------------------------------------------------

PERSISTENCE_KEY = "effect/ai/Chat/Persisted"
"""The provider-options key holding a persisted message's ``messageId``."""


class ChatNotFoundError(S.TaggedError, identifier="effect/ai/Chat/ChatNotFoundError"):
    """No chat is stored under ``chat_id``."""

    chat_id: str = S.field(S.String, key="chatId")


class Persisted(Service):
    """A chat kept in a store under ``id``; every call saves it, and
    ``save`` saves it now."""

    def __init__(
        self,
        id: str,
        history: Ref[P.Prompt],
        store: BackingPersistenceStore,
        ids: IdService,
        ttl: Duration | None,
    ) -> None:
        super().__init__(history, lambda before: self._save(before).or_die())
        self.id = id
        self._store = store
        self._ids = ids
        self._ttl = ttl

    @property
    def save(self) -> Effect[None, AiError | PersistenceError]:
        return self.history.get().flat_map(self._save)

    def _save(self, before: P.Prompt) -> Effect[None, AiError | PersistenceError]:
        """Tag the messages added since ``before`` with a message id (the
        last assistant message's in ``before``, else a new one), then store
        the history."""
        last = before.content[-1] if before.content else None
        tagged = last.options.get(PERSISTENCE_KEY) if isinstance(last, P.AssistantMessage) else None
        message_id = tagged.get("messageId") if isinstance(tagged, dict) else None
        id_effect = (
            fx.succeed(message_id) if isinstance(message_id, str) else self._ids.generate_id()
        )

        def store(id: str) -> Effect[None, AiError | PersistenceError]:
            def tag(history: P.Prompt) -> P.Prompt:
                kept = history.content[: len(before.content)]
                added = tuple(
                    replace(m, options={**m.options, PERSISTENCE_KEY: {"messageId": id}})
                    for m in history.content[len(before.content) :]
                )
                return P.Prompt((*kept, *added))

            return self.history.update(tag).and_then(
                self.export.or_die().flat_map(
                    lambda exported: self._store.set(self.id, exported, self._ttl)
                )
            )

        return id_effect.flat_map(store)


class PersistenceService:
    """Chats kept in one ``BackingPersistence`` store, by id."""

    def __init__(self, store: BackingPersistenceStore) -> None:
        self._store = store

    def _persisted(
        self, chat_id: str, history: P.Prompt, ttl: Duration | None
    ) -> Effect[Persisted]:
        return fx.service_option(IdGenerator).map(
            lambda found: Persisted(
                chat_id,
                Ref(history),
                self._store,
                found.value if found is not None else default_id_generator,
                ttl,
            )
        )

    def _get(
        self, chat_id: str, ttl: Duration | None
    ) -> Effect[Persisted, ChatNotFoundError | PersistenceError]:
        def found(stored: object | None) -> Effect[Persisted, ChatNotFoundError | PersistenceError]:
            if stored is None:
                return fx.fail(ChatNotFoundError(chat_id=chat_id))
            decoded = _decode(stored).map_error(
                lambda error: PersistenceError(
                    message=f'Failed to decode persisted history for chat "{chat_id}"', cause=error
                )
            )
            return decoded.flat_map(lambda history: self._persisted(chat_id, history, ttl))

        return self._store.get(chat_id).flat_map(found)

    def _create(self, chat_id: str, ttl: Duration | None) -> Effect[Persisted, PersistenceError]:
        exported = _encode(P.empty).or_die()
        return exported.flat_map(lambda e: self._store.set(chat_id, e, ttl)).and_then(
            self._persisted(chat_id, P.empty, ttl)
        )

    def get(
        self, chat_id: str, *, time_to_live: DurationInput | None = None
    ) -> Effect[Persisted, ChatNotFoundError | PersistenceError]:
        """The chat stored under ``chat_id``; its saves keep it for
        ``time_to_live`` (forever when ``None``)."""
        ttl = None if time_to_live is None else from_input_unsafe(time_to_live)
        return self._get(chat_id, ttl).with_span("PersistedChat.get")

    def get_or_create(
        self, chat_id: str, *, time_to_live: DurationInput | None = None
    ) -> Effect[Persisted, AiError | PersistenceError]:
        """The chat stored under ``chat_id``, or a new empty one stored
        there."""
        ttl = None if time_to_live is None else from_input_unsafe(time_to_live)
        got = self._get(chat_id, ttl).catch_all(
            lambda error: (
                self._create(chat_id, ttl)
                if isinstance(error, ChatNotFoundError)
                else fx.fail(error)
            )
        )
        return got.with_span("PersistedChat.getOrCreate")


class Persistence(Tag[PersistenceService], key="effect/ai/Chat/Persisted"):
    """Persisted chats."""


def make_persisted(
    *, store_id: str
) -> Effect[PersistenceService, Never, BackingPersistence | Scope]:
    """Chats in the backing store ``store_id``."""
    return (
        BackingPersistence()
        .flat_map(lambda backing: backing.make(store_id))
        .map(PersistenceService)
    )


def layer_persisted(*, store_id: str) -> Layer[Persistence, Never, BackingPersistence]:
    """``Persistence`` in the backing store ``store_id``."""
    return layer_effect(Persistence, make_persisted(store_id=store_id))


__all__ = [
    "PERSISTENCE_KEY",
    "AiError",
    "Chat",
    "ChatNotFoundError",
    "InterruptSafe",
    "Persisted",
    "Persistence",
    "PersistenceError",
    "PersistenceService",
    "SchemaError",
    "Service",
    "empty",
    "from_export",
    "from_json",
    "from_prompt",
    "interrupt_safe",
    "layer_persisted",
    "make_persisted",
]
