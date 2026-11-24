"""Typed buttons, selects, modals and slash commands, and the service that
receives their clicks, submits and commands (Effect's
``effect/chat/ChatInteraction``).

A definition carries an element's id and the schema of its value. It builds
the element to post (``of``, ``open``) and its handler (``handler``), the
way a ``Tool`` does. A ``group`` of definitions becomes a layer of handlers,
and ``chat_interaction.layer`` provides the ``Handler`` service adapters
call::

    Deploy = S.Struct(DeployDict)
    Reject = ci.button("reject", label="Reject", style="danger", value=Deploy)
    RejectReason = ci.modal(
        "reject-reason",
        title="Reject deploy",
        metadata=Deploy,
        fields={"reason": ci.text_input(label="Reason", multiline=True)},
    )
    interactions = ci.group(Reject, RejectReason).to_layer(
        Reject.handler(lambda click: fx.succeed(RejectReason.open(metadata=click.value))),
        RejectReason.handler(
            lambda submit: fx.succeed(
                ci.errors(reason="Say a bit more.")
                if len(submit.values["reason"]) < 10
                else ci.close
            )
        ),
    ).pipe(layer.provide_merge(ci.layer()))

- Clicks, submits and commands are not ``ChatEvent``s. They need an answer
  inside the platform's 3 seconds, so they go to ``Handler``, which answers
  by return value and has no error channel.
- Slack and Discord don't redeliver them, so they carry no dedupe key.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Never, TypeVar, cast, overload

import pyfect as fx
from pyfect import _json_text
from pyfect import schema as S
from pyfect._core import Effect, _call_user
from pyfect._fiber import Fiber
from pyfect._json_value import JsonValue
from pyfect.chat import chat_ui as U
from pyfect.chat.chat_error import INTERACTION_EXPIRED, ChatError, NotFound
from pyfect.chat.chat_thread import ChatThread
from pyfect.context import Context, Tag
from pyfect.duration import Input as DurationInput
from pyfect.exit import Exit, Success
from pyfect.layer import Layer
from pyfect.layer import effect_context as _layer_effect_context
from pyfect.layer import effect_discard as _layer_effect_discard
from pyfect.option import Option, Some
from pyfect.schema import ast as _ast
from pyfect.scope import Scope

# --- events --------------------------------------------------------------------------


class ButtonClicked(S.TaggedClass, tag="ButtonClicked"):
    """A click on a button. ``value`` is still encoded, ``None`` for a
    button with no value; ``thread`` and ``message_id`` are where the
    message carrying the button lives, ``raw`` the platform's payload. On a
    command's private answer no message op works with ``message_id``."""

    id: str
    value: str | None = None
    thread: ChatThread
    message_id: str = S.field(S.String, key="messageId")
    user_id: str = S.field(S.String, key="userId")
    raw: JsonValue


class SelectChanged(S.TaggedClass, tag="SelectChanged"):
    """A choice in a select on a message; ``value`` is the chosen option's
    value, still encoded."""

    id: str
    value: str
    thread: ChatThread
    message_id: str = S.field(S.String, key="messageId")
    user_id: str = S.field(S.String, key="userId")
    raw: JsonValue


class ModalSubmitted(S.TaggedClass, tag="ModalSubmitted"):
    """A modal submit. ``thread`` and ``message_id`` are those of the click
    that opened the modal (a command's modal has no ``message_id``);
    ``metadata`` and ``values`` (by field id; an optional field left empty
    has no key) are still encoded."""

    id: str
    metadata: str | None = None
    values: Mapping[str, str] = S.field(S.Record(S.String, S.String))
    thread: ChatThread
    message_id: str | None = S.field(S.NullOr(S.String), default=None, key="messageId")
    user_id: str = S.field(S.String, key="userId")
    raw: JsonValue


class CommandInvoked(S.TaggedClass, tag="CommandInvoked"):
    """A slash command. ``id`` is its name without the slash, ``text`` what
    was typed after it (empty when nothing was), ``thread`` where it was
    typed. ``raw`` holds what ``Chat.follow_up`` needs, so it is a
    credential for ``limits.follow_up_age``."""

    id: str
    text: str
    thread: ChatThread
    user_id: str = S.field(S.String, key="userId")
    raw: JsonValue


type Interaction = ButtonClicked | SelectChanged | ModalSubmitted | CommandInvoked
"""What an adapter hands to ``Handler``."""

INTERACTION: S.Bottom[Interaction] = cast(
    "S.Bottom[Interaction]", S.Union(ButtonClicked, SelectChanged, ModalSubmitted, CommandInvoked)
)

# --- replies -------------------------------------------------------------------------


class Ack(S.TaggedClass, tag="Ack"):
    """Acknowledges a click; also the answer to a command nobody handles,
    which the adapter sends nothing for."""


class OpenModal(S.TaggedClass, tag="OpenModal"):
    """Opens a modal; a click or a command can return it."""

    modal: U.Modal


class Close(S.TaggedClass, tag="Close"):
    """Closes a submitted modal."""


class Errors(S.TaggedClass, tag="Errors"):
    """Puts a message under each named field of a submitted modal
    (``errors`` by field id). Without ``modalErrors`` the adapter answers
    some other way."""

    errors: Mapping[str, str] = S.field(S.Record(S.String, S.String))


type ClickReply = Ack | OpenModal
type SubmitReply = Close | Errors

type Visibility = Literal["ephemeral", "public"]
"""Who sees a command's answer: the person who ran it, or the channel."""

VISIBILITY = S.Literals("ephemeral", "public")


class Respond(S.TaggedClass, tag="Respond"):
    """Answers a command with a message, at once. Rendered and checked as
    ``post`` renders and checks, with the default post options, so it never
    mentions anyone. The message gets no id."""

    markdown: str
    actions: tuple[U.Action, ...] | None = S.field(S.NullOr(S.Array(U.ACTION)), default=None)
    visibility: Visibility = S.field(VISIBILITY)


class Defer(S.TaggedClass, tag="Defer"):
    """Says a command's answer comes later, and is what ``Chat.follow_up``
    takes to send it. Plain data, so it can go on a queue; it holds the
    command's ``raw``, a credential for ``limits.follow_up_age``."""

    command: CommandInvoked
    visibility: Visibility = S.field(VISIBILITY)


type CommandReply = Ack | Respond | OpenModal | Defer


class Late(S.TaggedClass, tag="Late"):
    """What ``handle`` gives when the handler ran past the deadline. Never
    sent to a platform."""


ack = Ack()
close = Close()
late = Late()


def errors(fields: Mapping[str, str] | None = None, /, **by_field: str) -> Errors:
    """Puts a message under each named field of a submitted modal."""
    return Errors(errors={**(fields or {}), **by_field})


def respond(
    *,
    markdown: str,
    actions: Sequence[U.Action] | None = None,
    visibility: Visibility = "ephemeral",
) -> Respond:
    """Answers a command with a message, at once. ``visibility`` defaults to
    ``"ephemeral"``; a platform without ``ephemeral`` refuses a private
    answer and never sends it publicly instead."""
    return Respond(
        markdown=markdown,
        actions=None if actions is None else tuple(actions),
        visibility=visibility,
    )


def defer(command: CommandInvoked, *, visibility: Visibility = "ephemeral") -> Defer:
    """Answers a command with a promise of a later answer, sent with
    ``Chat.follow_up``, for work that does not fit the deadline.
    ``visibility`` holds for the follow-up. One follow-up per deferral is
    the portable contract."""
    return Defer(command=command, visibility=visibility)


# --- typed events --------------------------------------------------------------------

V_co = TypeVar("V_co", covariant=True)
M_co = TypeVar("M_co", covariant=True)


@dataclass(frozen=True, kw_only=True)
class Click(Generic[V_co]):
    """A click as a button's handler receives it: ``value`` decoded with the
    button's schema, ``None`` when it has none."""

    id: str
    value: V_co
    thread: ChatThread
    message_id: str
    user_id: str
    raw: JsonValue


@dataclass(frozen=True, kw_only=True)
class Selected(Generic[V_co]):
    """A choice as a select's handler receives it, the value decoded."""

    id: str
    value: V_co
    thread: ChatThread
    message_id: str
    user_id: str
    raw: JsonValue


@dataclass(frozen=True, kw_only=True)
class Submit(Generic[M_co]):
    """A submit as a modal's handler receives it: ``metadata`` decoded,
    ``values`` one per input decoded (``None`` for an optional input left
    empty, none for ``text``), ``message_id`` ``None`` when a command opened
    the modal."""

    id: str
    metadata: M_co
    values: Mapping[str, Any]
    thread: ChatThread
    message_id: str | None
    user_id: str
    raw: JsonValue


# --- values --------------------------------------------------------------------------

type ValueSchema[T] = S.Codec[T, Any, Never, Never]
"""A value's schema; it needs no services, since ``of`` and ``open`` are
plain functions."""


@dataclass(frozen=True)
class _Wire:
    raw: bool
    encode: Callable[[object], object]
    decode: Callable[[object], Option[object]]


_wires: dict[object, _Wire] = {}


def _string_only(node: _ast.AST) -> bool:
    if isinstance(node, (_ast.String, _ast.TemplateLiteral)):
        return True
    if isinstance(node, _ast.Literal):
        return isinstance(node.literal, str)
    if isinstance(node, _ast.Union):
        return len(node.types) > 0 and all(_string_only(t) for t in node.types)
    return False


def _wire_of(schema: ValueSchema[Any]) -> _Wire:
    wire = _wires.get(schema)
    if wire is None:
        codec = S.to_codec_json(schema)
        decode = S.decode_unknown_option(codec)

        def safe_decode(encoded: object) -> Option[object]:
            try:
                return decode(encoded)
            except Exception:
                return None

        wire = _Wire(
            raw=_string_only(S.to_encoded(codec).ast),
            encode=S.encode_unknown_sync(codec),
            decode=safe_decode,
        )
        _wires[schema] = wire
    return wire


def encode_value[T](schema: ValueSchema[T], value: T) -> str:
    """The string an element carries for ``value``. The form is decided once
    per schema from its JSON codec's encoded side: a string-only schema
    sends the string as it is, any other the JSON text. Raises when the
    value has no JSON form."""
    wire = _wire_of(schema)
    encoded = wire.encode(value)
    if wire.raw:
        return cast("str", encoded)
    return _json_text.stringify(encoded)


def decode_value[T](schema: ValueSchema[T], encoded: str) -> Option[T]:
    """The value an element carried, as ``encode_value`` wrote it; ``None``
    for a string that no longer decodes (one posted under an older
    schema)."""
    wire = _wire_of(schema)
    if wire.raw:
        return cast("Option[T]", wire.decode(encoded))
    try:
        parsed = _json_text.parse(encoded)
    except ValueError:
        return None
    return cast("Option[T]", wire.decode(parsed))


# --- definitions ---------------------------------------------------------------------

I_co = TypeVar("I_co", bound=str, covariant=True)
R_co = TypeVar("R_co", covariant=True)


@dataclass(frozen=True)
class Handled(Generic[I_co, R_co]):
    """A definition's handler, made by its ``handler`` method; ``R_co`` is
    the services it needs."""

    definition: Definition
    run: Callable[[Any], Effect[Any, Never, Any]]


@dataclass(frozen=True)
class Button(Generic[I_co, V_co]):
    """A button definition. ``of`` gives the element to post, taking the
    value when the definition has a schema for one; ``label`` and ``style``
    override this one element's. ``of`` raises when the value cannot be
    encoded."""

    id: I_co
    label: str
    style: U.ButtonStyle | None
    value: ValueSchema[Any] | None
    kind: Literal["button"] = field(default="button", init=False)

    @overload
    def of(
        self: Button[Any, None],
        /,
        *,
        label: str | None = None,
        style: U.ButtonStyle | None = None,
    ) -> U.Button: ...
    @overload
    def of[VV](
        self: Button[Any, VV],
        value: VV,
        /,
        *,
        label: str | None = None,
        style: U.ButtonStyle | None = None,
    ) -> U.Button: ...
    def of(
        self: Button[Any, Any],
        value: object = None,
        /,
        *,
        label: str | None = None,
        style: U.ButtonStyle | None = None,
    ) -> U.Button:
        return U.Button(
            id=self.id,
            label=self.label if label is None else label,
            style=style if style is not None else self.style,
            value=None if self.value is None else encode_value(self.value, value),
        )

    def handler[VV, RR = Never](
        self: Button[I_co, VV], fn: Callable[[Click[VV]], Effect[ClickReply, Never, RR]]
    ) -> Handled[I_co, RR]:
        """This button's handler: it answers ``ack`` or a modal to open."""
        return Handled(cast("Definition", self), fn)


@overload
def button[I: str](id: I, *, label: str, style: U.ButtonStyle | None = None) -> Button[I, None]: ...
@overload
def button[I: str, T](
    id: I, *, label: str, style: U.ButtonStyle | None = None, value: ValueSchema[T]
) -> Button[I, T]: ...
def button(
    id: str,
    *,
    label: str,
    style: U.ButtonStyle | None = None,
    value: ValueSchema[Any] | None = None,
) -> Button[Any, Any]:
    """Defines a button. The id names its handler in a ``group`` and is sent
    to the platform as is, counting toward ``limits.action_data_length``
    with the encoded value. With no ``value`` schema a click's value is
    ``None``."""
    return Button(id, label, style, value)


@dataclass(frozen=True, kw_only=True)
class OptionOf(Generic[V_co]):
    """One option of a select definition: a label and its (typed) value."""

    label: str
    value: V_co


@dataclass(frozen=True)
class Select(Generic[I_co, V_co]):
    """A select definition for a message; its options are given to ``of``.
    ``of`` raises when an option's value cannot be encoded."""

    id: I_co
    placeholder: str | None
    value: ValueSchema[Any] | None
    kind: Literal["select"] = field(default="select", init=False)

    def _encode(self, option: object) -> str:
        return cast("str", option) if self.value is None else encode_value(self.value, option)

    def of[VV](
        self: Select[Any, VV], *, options: Sequence[OptionOf[VV]], selected: VV | None = None
    ) -> U.Select:
        me = cast("Select[Any, Any]", self)
        return U.Select(
            id=self.id,
            placeholder=self.placeholder,
            options=tuple(
                U.SelectOption(label=o.label, value=me._encode(o.value)) for o in options
            ),
            selected=None if selected is None else me._encode(selected),
        )

    def handler[VV, RR = Never](
        self: Select[I_co, VV], fn: Callable[[Selected[VV]], Effect[ClickReply, Never, RR]]
    ) -> Handled[I_co, RR]:
        """This select's handler: it answers ``ack`` or a modal to open."""
        return Handled(cast("Definition", self), fn)


@overload
def select[I: str](id: I, *, placeholder: str | None = None) -> Select[I, str]: ...
@overload
def select[I: str, T](
    id: I, *, placeholder: str | None = None, value: ValueSchema[T]
) -> Select[I, T]: ...
def select(
    id: str, *, placeholder: str | None = None, value: ValueSchema[Any] | None = None
) -> Select[Any, Any]:
    """Defines a single-choice select for a message. With no ``value``
    schema the options' values are plain strings."""
    return Select(id, placeholder, value)


@dataclass(frozen=True, kw_only=True)
class TextInput:
    """A text input field of a modal, one line or several; its value is a
    ``str`` (``None`` when optional and left empty)."""

    label: str
    multiline: bool = False
    placeholder: str | None = None
    optional: bool = False
    min_length: int | None = None
    max_length: int | None = None
    kind: Literal["textInput"] = field(default="textInput", init=False)


def text_input(
    *,
    label: str,
    multiline: bool = False,
    placeholder: str | None = None,
    optional: bool = False,
    min_length: int | None = None,
    max_length: int | None = None,
) -> TextInput:
    """Defines a text input for a modal; its id is its key in ``fields``."""
    return TextInput(
        label=label,
        multiline=multiline,
        placeholder=placeholder,
        optional=optional,
        min_length=min_length,
        max_length=max_length,
    )


@dataclass(frozen=True, kw_only=True)
class Choice:
    """A select field of a modal whose options are fixed in the definition;
    its value is one of the option values."""

    label: str
    placeholder: str | None = None
    options: tuple[OptionOf[str], ...]
    optional: bool = False
    kind: Literal["choice"] = field(default="choice", init=False)


def choice(
    *,
    label: str,
    options: Sequence[OptionOf[str]],
    placeholder: str | None = None,
    optional: bool = False,
) -> Choice:
    """Defines a select for a modal whose options are fixed here."""
    return Choice(label=label, placeholder=placeholder, options=tuple(options), optional=optional)


@dataclass(frozen=True, kw_only=True)
class SelectInput:
    """A select field of a modal whose options are given to ``open``."""

    label: str
    placeholder: str | None = None
    value: ValueSchema[Any] | None = None
    optional: bool = False
    kind: Literal["selectInput"] = field(default="selectInput", init=False)


def select_input(
    *,
    label: str,
    placeholder: str | None = None,
    value: ValueSchema[Any] | None = None,
    optional: bool = False,
) -> SelectInput:
    """Defines a select for a modal; its id is its key in ``fields`` and its
    options are given to the modal's ``open``."""
    return SelectInput(label=label, placeholder=placeholder, value=value, optional=optional)


@dataclass(frozen=True)
class Text:
    """Plain text between a modal's inputs; it has no value."""

    text: str
    kind: Literal["text"] = field(default="text", init=False)


def text(text: str) -> Text:
    """Defines plain (not Markdown) text for a modal."""
    return Text(text)


type Field = TextInput | Choice | SelectInput | Text
"""Any field of a modal."""


@dataclass(frozen=True)
class Modal(Generic[I_co, M_co]):
    """A modal definition. ``open`` gives the reply that opens it; it raises
    when the metadata or an option's value cannot be encoded."""

    id: I_co
    title: str
    submit_label: str | None
    metadata: ValueSchema[Any] | None
    fields: Mapping[str, Field]
    kind: Literal["modal"] = field(default="modal", init=False)

    @overload
    def open(
        self: Modal[Any, None],
        *,
        options: Mapping[str, Sequence[OptionOf[Any]]] | None = None,
        initial: Mapping[str, object] | None = None,
    ) -> OpenModal: ...
    @overload
    def open[MM](
        self: Modal[Any, MM],
        *,
        metadata: MM,
        options: Mapping[str, Sequence[OptionOf[Any]]] | None = None,
        initial: Mapping[str, object] | None = None,
    ) -> OpenModal: ...
    def open(
        self,
        *,
        metadata: object = None,
        options: Mapping[str, Sequence[OptionOf[Any]]] | None = None,
        initial: Mapping[str, object] | None = None,
    ) -> OpenModal:
        elements: list[U.ModalElement] = []
        for name, definition in self.fields.items():
            first = None if initial is None else initial.get(name)
            match definition:
                case Text():
                    elements.append(U.Text(text=definition.text))
                case TextInput():
                    elements.append(
                        U.TextInput(
                            id=name,
                            label=definition.label,
                            multiline=definition.multiline,
                            placeholder=definition.placeholder,
                            initial=cast("str | None", first),
                            optional=definition.optional,
                            min_length=definition.min_length,
                            max_length=definition.max_length,
                        )
                    )
                case Choice() | SelectInput():
                    schema = definition.value if isinstance(definition, SelectInput) else None

                    def encode(value: object, schema: ValueSchema[Any] | None = schema) -> str:
                        return cast("str", value) if schema is None else encode_value(schema, value)

                    choices: Sequence[OptionOf[Any]] = (
                        definition.options
                        if isinstance(definition, Choice)
                        else (() if options is None else options.get(name, ()))
                    )
                    elements.append(
                        U.SelectInput(
                            id=name,
                            label=definition.label,
                            placeholder=definition.placeholder,
                            options=tuple(
                                U.SelectOption(label=o.label, value=encode(o.value))
                                for o in choices
                            ),
                            initial=None if first is None else encode(first),
                            optional=definition.optional,
                        )
                    )
        return OpenModal(
            modal=U.Modal(
                id=self.id,
                title=self.title,
                submit_label=self.submit_label,
                metadata=None if self.metadata is None else encode_value(self.metadata, metadata),
                elements=tuple(elements),
            )
        )

    def handler[MM, RR = Never](
        self: Modal[I_co, MM], fn: Callable[[Submit[MM]], Effect[SubmitReply, Never, RR]]
    ) -> Handled[I_co, RR]:
        """This modal's submit handler: it answers ``close`` or ``errors``
        naming its own inputs."""
        return Handled(cast("Definition", self), fn)


@overload
def modal[I: str](
    id: I, *, title: str, fields: Mapping[str, Field], submit_label: str | None = None
) -> Modal[I, None]: ...
@overload
def modal[I: str, T](
    id: I,
    *,
    title: str,
    fields: Mapping[str, Field],
    metadata: ValueSchema[T],
    submit_label: str | None = None,
) -> Modal[I, T]: ...
def modal(
    id: str,
    *,
    title: str,
    fields: Mapping[str, Field],
    metadata: ValueSchema[Any] | None = None,
    submit_label: str | None = None,
) -> Modal[Any, Any]:
    """Defines a modal. The id names the submit's handler; with the encoded
    metadata it counts toward ``limits.modal_metadata_length``, and inputs
    and texts toward ``limits.modal_fields``. A portable modal has a title
    of 24 or less, labels of 45 or less, at most 5 fields, and an id plus
    metadata under 100 characters."""
    return Modal(id, title, submit_label, metadata, dict(fields))


@dataclass(frozen=True, kw_only=True)
class CommandArgument:
    """A command's one text argument, for registration."""

    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class Command(Generic[I_co]):
    """A slash command definition: a name and at most one text argument.
    ``description`` and ``argument`` are what registration needs (Slack
    reads its own from the app manifest)."""

    id: I_co
    description: str
    argument: CommandArgument | None
    kind: Literal["command"] = field(default="command", init=False)

    def handler[RR = Never](
        self, fn: Callable[[CommandInvoked], Effect[Respond | OpenModal | Defer, Never, RR]]
    ) -> Handled[I_co, RR]:
        """This command's handler: it answers ``respond``, a modal to open
        or ``defer``, never ``ack``."""
        return Handled(cast("Definition", self), fn)


def command[I: str](
    id: I, *, description: str, argument: CommandArgument | None = None
) -> Command[I]:
    """Defines a slash command; the id is its name without the slash and
    shares the registry's id space with buttons, selects and modals. Slack
    sends everything after the name as one string and cannot enforce
    ``required``, so a portable handler checks for an empty ``text``."""
    return Command(id, description, argument)


type Definition = Button[str, Any] | Select[str, Any] | Modal[str, Any] | Command[str]
"""Any definition that has a handler."""

# --- decoding ------------------------------------------------------------------------


def _matches(definition: Definition, event: Interaction) -> bool:
    match event:
        case ButtonClicked():
            return isinstance(definition, Button)
        case SelectChanged():
            return isinstance(definition, Select)
        case ModalSubmitted():
            return isinstance(definition, Modal)
        case CommandInvoked():
            return isinstance(definition, Command)


_MISSING_VALUE = object()


def _decode_field(f: TextInput | Choice | SelectInput, encoded: str | None) -> object:
    """A field's decoded value, or ``_MISSING_VALUE`` when it does not decode."""
    if encoded is None:
        return None if f.optional else _MISSING_VALUE
    if isinstance(f, Choice) and not any(o.value == encoded for o in f.options):
        return _MISSING_VALUE
    if not isinstance(f, SelectInput) or f.value is None:
        return encoded
    found = decode_value(f.value, encoded)
    return _MISSING_VALUE if found is None else found.value


def _decode_submit(definition: Modal[str, Any], event: ModalSubmitted) -> Option[object]:
    metadata: object = None
    if definition.metadata is not None:
        decoded = (
            None if event.metadata is None else decode_value(definition.metadata, event.metadata)
        )
        if decoded is None:
            return None
        metadata = decoded.value
    values: dict[str, object] = {}
    for name, f in definition.fields.items():
        if isinstance(f, Text):
            continue
        value = _decode_field(f, event.values.get(name))
        if value is _MISSING_VALUE:
            return None
        values[name] = value
    return Some(
        Submit(
            id=event.id,
            metadata=metadata,
            values=values,
            thread=event.thread,
            message_id=event.message_id,
            user_id=event.user_id,
            raw=event.raw,
        )
    )


def _decode_click(definition: Definition, event: ButtonClicked) -> Option[object]:
    if not isinstance(definition, Button):
        return None
    if definition.value is None:
        value: Option[object] = Some(None)
    else:
        value = None if event.value is None else decode_value(definition.value, event.value)
    if value is None:
        return None
    return Some(
        Click(
            id=event.id,
            value=value.value,
            thread=event.thread,
            message_id=event.message_id,
            user_id=event.user_id,
            raw=event.raw,
        )
    )


def _decode_selected(definition: Definition, event: SelectChanged) -> Option[object]:
    if not isinstance(definition, Select):
        return None
    chosen: Option[object] = (
        Some(event.value)
        if definition.value is None
        else decode_value(definition.value, event.value)
    )
    if chosen is None:
        return None
    return Some(
        Selected(
            id=event.id,
            value=chosen.value,
            thread=event.thread,
            message_id=event.message_id,
            user_id=event.user_id,
            raw=event.raw,
        )
    )


def _decode_event(definition: Definition, event: Interaction) -> Option[object]:
    """The event as the definition's handler takes it, or ``None`` when its
    value no longer decodes."""
    match event:
        case ButtonClicked():
            return _decode_click(definition, event)
        case SelectChanged():
            return _decode_selected(definition, event)
        case ModalSubmitted():
            return _decode_submit(definition, event) if isinstance(definition, Modal) else None
        case CommandInvoked():
            return Some(event) if isinstance(definition, Command) else None


def _fallback(event: Interaction) -> Ack | Close:
    return close if isinstance(event, ModalSubmitted) else ack


type _AnyReply = ClickReply | SubmitReply | CommandReply

# --- the handler service and the registry --------------------------------------------


@dataclass(frozen=True)
class Registered:
    """One registered definition with its handler, services provided.
    ``handle`` answers ``ack`` or ``close`` without calling the handler when
    the event does not match or its value no longer decodes."""

    definition: Definition
    handle: Callable[[Interaction], Effect[_AnyReply]]


class RegistryService:
    """Where groups put their handlers; ``register`` dies when an id is
    already registered."""

    __slots__ = ("_entries",)

    def __init__(self, entries: dict[str, Registered]) -> None:
        self._entries = entries

    def register(self, registered: Sequence[Registered]) -> Effect[None]:
        """Registers handlers; dies when an id is already registered."""

        def run() -> Effect[None]:
            ids: set[str] = set()
            for entry in registered:
                id = entry.definition.id
                if id in self._entries or id in ids:
                    return fx.die(
                        ValueError(f'ChatInteraction: the id "{id}" is already registered')
                    )
                ids.add(id)
            for entry in registered:
                self._entries[entry.definition.id] = entry
            return fx.void

        return fx.suspend(run)

    def get(self, id: str) -> Effect[Registered | None]:
        """The handler registered for ``id``, or ``None``."""
        return fx.sync(lambda: self._entries.get(id))


class Registry(Tag[RegistryService], key="effect/chat/ChatInteraction/Registry"):
    """Where groups put their handlers; ``chat_interaction.layer`` provides it."""


@dataclass(frozen=True)
class Group(Generic[I_co]):
    """Definitions whose handlers are registered together. ``to_layer``
    registers the handlers (it needs the ``Registry``); every definition
    needs exactly one. Two definitions with one id, in one group or across
    groups, are a defect when the layer is built."""

    definitions: tuple[Definition, ...]

    def add(self, *definitions: Definition) -> Group[str]:
        return Group((*self.definitions, *definitions))

    def merge(self, *groups: Group[str]) -> Group[str]:
        return Group((*self.definitions, *(d for g in groups for d in g.definitions)))

    @overload
    def to_layer[RR](self, *handlers: Handled[str, RR]) -> Layer[Never, Never, RR | Registry]: ...
    @overload
    def to_layer[RR, EX, RX](
        self, handlers: Effect[Iterable[Handled[str, RR]], EX, RX | Scope], /
    ) -> Layer[Never, EX, RR | RX | Registry]: ...
    def to_layer(self, *handlers: Any) -> Layer[Any, Any, Any]:
        build: Effect[Iterable[Handled[str, Any]], Any, Any] = (
            cast("Effect[Iterable[Handled[str, Any]], Any, Any]", handlers[0])
            if len(handlers) == 1 and isinstance(handlers[0], Effect)
            else fx.succeed(cast("tuple[Handled[str, Any], ...]", handlers))
        )
        definitions = self.definitions

        def register(made: Iterable[Handled[str, Any]]) -> Effect[None, Never, Registry]:
            by_id = _handlers_by_id(definitions, tuple(made))
            return fx.context().flat_map(
                lambda context: Registry().flat_map(
                    lambda registry: registry.register(
                        [_registered(d, by_id[d.id], context) for d in definitions]
                    )
                )
            )

        return _layer_effect_discard(build.flat_map(register))


def _handlers_by_id(
    definitions: Sequence[Definition], handlers: Sequence[Handled[str, Any]]
) -> dict[str, Handled[str, Any]]:
    by_id: dict[str, Handled[str, Any]] = {}
    for handler in handlers:
        if handler.definition.id in by_id:
            raise ValueError(f'ChatInteraction: two handlers for "{handler.definition.id}"')
        by_id[handler.definition.id] = handler
    known = {d.id for d in definitions}
    missing = [d.id for d in definitions if d.id not in by_id]
    extra = [id for id in by_id if id not in known]
    if missing or extra:
        raise ValueError(
            f"ChatInteraction: handlers missing for {missing} and given for unknown ids {extra}"
        )
    return by_id


def _registered(
    definition: Definition, handler: Handled[str, Any], context: Context[Any]
) -> Registered:
    def handle(event: Interaction) -> Effect[_AnyReply]:
        typed = _decode_event(definition, event)
        if typed is None:
            return fx.succeed(_fallback(event))
        return _call_user(handler.run, typed.value).pipe(fx.provide_context(context))

    return Registered(definition, handle)


def group(*definitions: Definition) -> Group[str]:
    """Groups definitions so their handlers can be registered together."""
    return Group(definitions)


class HandlerService:
    """What an adapter calls with an interaction (public, for a consumer
    that routes clicks itself). The contract is to answer inside the
    platform's 3 seconds, with no error channel. ``refused`` is called when
    a click's or a command's reply was not carried out (no modal opened, a
    private answer without ``ephemeral``, a refusal by the platform, or a
    reply past the deadline)."""

    __slots__ = ("_click", "_command", "_refused", "_submit")

    def __init__(
        self,
        *,
        click: Callable[[ButtonClicked | SelectChanged], Effect[ClickReply]],
        submit: Callable[[ModalSubmitted], Effect[SubmitReply]],
        command: Callable[[CommandInvoked], Effect[CommandReply]],
        refused: Callable[
            [ButtonClicked | SelectChanged | CommandInvoked, ChatError], Effect[None]
        ],
    ) -> None:
        self._click = click
        self._submit = submit
        self._command = command
        self._refused = refused

    def click(self, event: ButtonClicked | SelectChanged) -> Effect[ClickReply]:
        """The reply to a button click or a select change."""
        return self._click(event)

    def submit(self, event: ModalSubmitted) -> Effect[SubmitReply]:
        """The reply to a modal submit."""
        return self._submit(event)

    def command(self, event: CommandInvoked) -> Effect[CommandReply]:
        """The reply to a slash command."""
        return self._command(event)

    def refused(
        self, event: ButtonClicked | SelectChanged | CommandInvoked, error: ChatError
    ) -> Effect[None]:
        """Reports that a click's or a command's reply was not carried out."""
        return self._refused(event, error)


class Handler(Tag[HandlerService], key="effect/chat/ChatInteraction/Handler"):
    """The service adapters hand interactions to."""


def _late_click(event: ButtonClicked | SelectChanged) -> ChatError:
    return ChatError(
        platform=event.thread.platform,
        op="openModal",
        reason=NotFound(detail=INTERACTION_EXPIRED),
    )


@overload
def handle(
    event: ButtonClicked | SelectChanged, deadline: DurationInput
) -> Effect[ClickReply | Late, Never, Handler]: ...
@overload
def handle(
    event: ModalSubmitted, deadline: DurationInput
) -> Effect[SubmitReply | Late, Never, Handler]: ...
@overload
def handle(
    event: CommandInvoked, deadline: DurationInput
) -> Effect[CommandReply | Late, Never, Handler]: ...
@overload
def handle(
    event: Interaction, deadline: DurationInput
) -> Effect[_AnyReply | Late, Never, Handler]: ...
def handle(event: Interaction, deadline: DurationInput) -> Effect[Any, Never, Handler]:
    """Calls the ``Handler`` service and gives the reply, or ``Late`` when
    ``deadline`` (the handler's share of the platform's 3 seconds) passes
    first; adapters and ``ChatTest`` call it.

    - A late click leaves its handler running, detached. When it later
      returns ``OpenModal`` the modal is dropped and ``Handler.refused`` gets
      a ``ChatError`` with reason ``NotFound``, op ``openModal``, detail
      ``interaction_expired``.
    - A late submit or command interrupts its handler; ``Late`` is given at
      the deadline without waiting for its finalizers.
    """

    def body(restore: fx.Restore) -> Effect[Any, Never, Handler]:
        def with_handler(handler: HandlerService) -> Effect[_AnyReply | Late]:
            work: Effect[_AnyReply] = (
                handler.submit(event)
                if isinstance(event, ModalSubmitted)
                else handler.command(event)
                if isinstance(event, CommandInvoked)
                else handler.click(event)
            )
            # Detached, so the reply at the deadline waits for neither a late click nor a
            # late submit's cleanup.
            return work.fork_daemon().flat_map(lambda fiber: wait(handler, fiber))

        def wait(
            handler: HandlerService, fiber: Fiber[_AnyReply, Never]
        ) -> Effect[_AnyReply | Late]:
            timed: Effect[Option[Exit[_AnyReply, Never]]] = restore(
                fiber.await_exit().timeout_option(deadline)
            )
            return timed.on_interrupt(fiber.interrupt()).flat_map(
                lambda exit: fx.from_exit(exit.value) if exit is not None else after(handler, fiber)
            )

        def after(handler: HandlerService, fiber: Fiber[_AnyReply, Never]) -> Effect[Late]:
            if not isinstance(event, (ButtonClicked, SelectChanged)):
                # Interrupt without delaying the deadline reply.
                return fiber.interrupt().fork_daemon().as_(late)
            clicked = event

            def refuse(done: Exit[_AnyReply, Never]) -> Effect[None]:
                if isinstance(done, Success) and isinstance(done.value, OpenModal):
                    return handler.refused(clicked, _late_click(clicked))
                return fx.void

            return fiber.await_exit().flat_map(refuse).fork_daemon().as_(late)

        return Handler().flat_map(with_handler)

    return fx.uninterruptible_mask(body)


@dataclass(frozen=True)
class Unhandled:
    """Why an interaction reached no handler, or why its reply was not
    carried out: ``UnknownId`` (no definition of that id and kind),
    ``InvalidValue`` (the value or metadata no longer decodes, or a required
    input is missing) or ``ReplyRefused`` (``Handler.refused`` was called,
    with the adapter's ``error``)."""

    reason: Literal["UnknownId", "InvalidValue", "ReplyRefused"]
    error: ChatError | None = None


def layer[R = Never](
    *, unhandled: Callable[[Interaction, Unhandled], Effect[None, Never, R]] | None = None
) -> Layer[Handler | Registry, Never, R]:
    """The ``Handler`` that routes by id to the registered definitions, and
    an empty ``Registry``; group layers go on top with
    ``layer.provide_merge``.

    - An interaction with an unknown id, or a value that no longer decodes,
      is logged and answered ``ack`` or ``close``; ``unhandled`` sees it
      first and cannot change the answer.
    - A command with an unknown id is answered ``ack`` (the adapter sends
      nothing) and logged at debug level.
    - ``Handler.refused`` goes to ``unhandled`` as ``ReplyRefused``, and is
      logged.
    """

    def make(context: Context[R]) -> Context[Handler | Registry]:
        entries: dict[str, Registered] = {}

        def report(event: Interaction, why: Unhandled, message: str) -> Effect[None]:
            seen: Effect[None] = (
                fx.void
                if unhandled is None
                else _call_user(unhandled, event, why).pipe(fx.provide_context(context))
            )
            log = (
                fx.log_debug(message)
                if isinstance(event, CommandInvoked) and why.reason == "UnknownId"
                else fx.log_warning(message)
            )
            return seen.and_then(
                log.annotate_logs(
                    {
                        "chat.platform": event.thread.platform,
                        "chat.interaction.id": event.id,
                        "chat.interaction.reason": why.reason,
                    }
                )
            )

        def route(event: Interaction) -> Effect[_AnyReply]:
            def run() -> Effect[_AnyReply]:
                entry = entries.get(event.id)
                if entry is None or not _matches(entry.definition, event):
                    return report(
                        event, Unhandled("UnknownId"), "ChatInteraction: no handler for this id"
                    ).as_(_fallback(event))
                if _decode_event(entry.definition, event) is None:
                    return report(
                        event,
                        Unhandled("InvalidValue"),
                        "ChatInteraction: the value no longer decodes",
                    ).as_(_fallback(event))
                return entry.handle(event)

            return fx.suspend(run)

        def refused(
            event: ButtonClicked | SelectChanged | CommandInvoked, error: ChatError
        ) -> Effect[None]:
            return report(
                event,
                Unhandled("ReplyRefused", error),
                "ChatInteraction: the reply was not carried out",
            ).annotate_logs("chat.error", error.message)

        handler = HandlerService(
            click=cast("Callable[[ButtonClicked | SelectChanged], Effect[ClickReply]]", route),
            submit=cast("Callable[[ModalSubmitted], Effect[SubmitReply]]", route),
            command=cast("Callable[[CommandInvoked], Effect[CommandReply]]", route),
            refused=refused,
        )
        return Context.make(Handler, handler).add(Registry, RegistryService(entries))

    return _layer_effect_context(fx.context().map(make))  # pyright: ignore[reportArgumentType]


__all__ = [
    "INTERACTION",
    "VISIBILITY",
    "Ack",
    "Button",
    "ButtonClicked",
    "Choice",
    "Click",
    "ClickReply",
    "Close",
    "Command",
    "CommandArgument",
    "CommandInvoked",
    "CommandReply",
    "Defer",
    "Definition",
    "Errors",
    "Field",
    "Group",
    "Handled",
    "Handler",
    "HandlerService",
    "Interaction",
    "Late",
    "Modal",
    "ModalSubmitted",
    "OpenModal",
    "OptionOf",
    "Registered",
    "Registry",
    "RegistryService",
    "Respond",
    "Select",
    "SelectChanged",
    "SelectInput",
    "Selected",
    "Submit",
    "SubmitReply",
    "Text",
    "TextInput",
    "Unhandled",
    "ValueSchema",
    "Visibility",
    "ack",
    "button",
    "choice",
    "close",
    "command",
    "decode_value",
    "defer",
    "encode_value",
    "errors",
    "group",
    "handle",
    "late",
    "layer",
    "modal",
    "respond",
    "select",
    "select_input",
    "text",
    "text_input",
]
