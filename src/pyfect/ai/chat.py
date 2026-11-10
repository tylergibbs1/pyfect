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
from dataclasses import replace
from typing import Any, Literal, LiteralString, Never, cast, overload

import pyfect as fx
from pyfect import schema as S
from pyfect._concurrency import Concurrency
from pyfect._core import Effect
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import toolkit as K
from pyfect.ai.ai_error import AiError, InvalidOutputError
from pyfect.ai.id_generator import IdGenerator, default_id_generator
from pyfect.ai.id_generator import Service as IdService
from pyfect.channel import acquire_use_release
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.effect import sync
from pyfect.exit import Exit
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
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
        self, prompt: P.RawInput, call: Callable[[P.Prompt], Effect[A, E, RR]]
    ) -> Effect[A, E, RR]:
        """``call`` with the history plus ``prompt``; the history then gains
        the response's parts."""

        def run(history: P.Prompt) -> Effect[A, E, RR]:
            full = history.concat(prompt)
            return call(full).flat_map(
                lambda response: self.history.set(
                    full.concat(P.from_response_parts(cast("list[R.AnyPart]", response.content)))
                ).as_(response)
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
            lambda full: _model().flat_map(
                lambda model: model.generate_text(
                    full,
                    toolkit=toolkit,
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
    ) -> Effect[lm.GenerateObjectResponse[NN, RP, A], AiError | EE, lm.LanguageModel | RR]: ...
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
    ) -> Effect[Any, Any, Any]:
        """``language_model.generate_object`` on the history plus ``prompt``."""
        call = self._call(
            prompt,
            lambda full: _model().flat_map(
                lambda model: model.generate_object(
                    full,
                    schema=schema,
                    object_name=object_name,
                    toolkit=toolkit,
                    tool_choice=tool_choice,
                    concurrency=concurrency,
                    disable_tool_call_resolution=disable_tool_call_resolution,
                    tool_call_validation=tool_call_validation,
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
    ) -> Stream[Any, Any, Any]:
        """``language_model.stream_text`` on the history plus ``prompt``.
        The history gains the parts streamed, also when the stream is cut
        short."""

        def start() -> Stream[Any, Any, Any]:
            parts: list[Any] = []

            def collect(chunk: tuple[Any, ...]) -> tuple[Any, ...]:
                parts.extend(chunk)
                return chunk

            def use(full: P.Prompt) -> Any:
                streamed = StreamC.unwrap(
                    _model().map(
                        lambda model: model.stream_text(
                            full,
                            toolkit=toolkit,
                            tool_choice=tool_choice,
                            concurrency=concurrency,
                            disable_tool_call_resolution=disable_tool_call_resolution,
                            tool_call_validation=tool_call_validation,
                        )
                    )
                )
                return to_channel(streamed.map_array(collect))

            def release(full: P.Prompt, _: Exit[Any, Any]) -> Effect[object]:
                done = full.concat(P.from_response_parts(parts))
                return self.history.set(done).and_then(self._lock.release(1))

            acquire = (
                self._lock.take(1).and_then(self.history.get()).map(lambda h: h.concat(prompt))
            )
            # Effect's Channel.acquireUseRelease: the history is set when the
            # model's stream ends, before any finalizer added outside (the save).
            return from_channel(acquire_use_release(acquire, use, release))

        stream = StreamC.unwrap(fx.sync(start)).with_span("Chat.streamText")
        after = self._after_call
        if after is None:
            return stream
        return StreamC.unwrap(self.history.get().map(lambda before: stream.ensuring(after(before))))


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
    "layer_persisted",
    "make_persisted",
]
