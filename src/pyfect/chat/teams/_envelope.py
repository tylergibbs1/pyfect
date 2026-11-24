"""The envelope a button or dialog carries in its ``effect`` data key: a
compact HS256 JWT bound to the bot, the tenant and the conversation. A
dialog token also binds the user it opened for and holds the modal's
definition, so a submit is checked against what was signed."""

from __future__ import annotations

import math
import re
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect._json_text import stringify
from pyfect._text_keys import key_bytes
from pyfect.chat.chat_error import AnyReason
from pyfect.chat.chat_ui import Button as UiButton
from pyfect.chat.chat_ui import Modal, ModalElement, SelectInput, SelectOption, Text, TextInput
from pyfect.chat.teams._address import MAX_ID_LENGTH, base_conversation
from pyfect.chat.teams._errors import invalid_request, too_large
from pyfect.clock import current_time_millis
from pyfect.crypto import digest as _digest
from pyfect.crypto.digest import Digest
from pyfect.crypto.mac import Mac
from pyfect.duration import Duration, hours
from pyfect.encoding import base64_url
from pyfect.jose import jwk, jwt
from pyfect.jose.jwk import HmacKey, SecretJwk
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

RESERVED_KEY = "effect"
"""The data key that holds the token. A modal field may not use it."""


@dataclass(frozen=True)
class _Limits:
    """Bounds on what a token holds, in characters. ``definition`` bounds the
    UTF-8 bytes of a modal's JSON without its metadata."""

    id: int = MAX_ID_LENGTH
    kid: int = 16
    button_value: int = 2_000
    metadata: int = 2_800
    text: int = 4_000
    fields: int = 100
    options: int = 100
    definition: int = 16_000


LIMITS = _Limits()

DEFAULT_MAX_LENGTH = LIMITS.text
"""The default max length of a text input."""

DEFAULT_DIALOG_TTL = hours(1)
"""How long a dialog token is good for when the caller gives no ttl."""

_TYP_BUTTON = "teams-button"
_TYP_DIALOG = "teams-dialog"
_MAX_SAFE_INTEGER = 2**53 - 1

# --- schemas ---------------------------------------------------------------------------


def _bounded(max_length: int) -> S.Codec[str, str, Never, Never]:
    return S.String.check(S.is_max_length(max_length))


_ID = _bounded(LIMITS.id)
_TEXT = _bounded(LIMITS.text)
_HASH = S.String.check(S.is_between_length(43, 43))
_LENGTH = S.Int.check(S.is_between(minimum=0, maximum=LIMITS.text))


class _OptionDef(TypedDict):
    label: str
    value: str


class _TextInputDef(TypedDict):
    _tag: Literal["TextInput"]
    id: str
    label: str
    multiline: NotRequired[bool]
    placeholder: NotRequired[str]
    initial: NotRequired[str]
    optional: NotRequired[bool]
    minLength: NotRequired[int]
    maxLength: NotRequired[int]


class _SelectInputDef(TypedDict):
    _tag: Literal["SelectInput"]
    id: str
    label: str
    placeholder: NotRequired[str]
    options: Sequence[_OptionDef]
    initial: NotRequired[str]
    optional: NotRequired[bool]


class _TextDef(TypedDict):
    _tag: Literal["Text"]
    text: str


type _ElementDef = _TextInputDef | _SelectInputDef | _TextDef


class Definition(TypedDict):
    """A modal without its metadata, as a dialog token holds it."""

    _tag: Literal["Modal"]
    id: str
    title: str
    submitLabel: NotRequired[str]
    elements: Sequence[_ElementDef]


_OPTION = S.Struct(_OptionDef, label=_TEXT, value=_TEXT)
_ELEMENT = S.Union(
    S.Struct(
        _TextInputDef,
        id=_ID,
        label=_TEXT,
        placeholder=_TEXT,
        initial=_TEXT,
        minLength=_LENGTH,
        maxLength=_LENGTH,
    ),
    S.Struct(
        _SelectInputDef,
        id=_ID,
        label=_TEXT,
        placeholder=_TEXT,
        options=S.Array(_OPTION).check(S.is_max_length(LIMITS.options)),
        initial=_TEXT,
    ),
    S.Struct(_TextDef, text=_TEXT),
)
DEFINITION = S.Struct(
    Definition,
    id=_ID,
    title=_TEXT,
    submitLabel=_TEXT,
    elements=S.Array(_ELEMENT).check(S.is_max_length(LIMITS.fields)),
)


class _ButtonClaims(TypedDict):
    aud: str
    tid: str
    cnv: str
    id: str
    val: NotRequired[str]


_BUTTON_CLAIMS = S.Struct(
    _ButtonClaims, aud=_ID, tid=_ID, cnv=_HASH, id=_ID, val=_bounded(LIMITS.button_value)
)

_DialogClaims = TypedDict(
    "_DialogClaims",
    {
        "aud": str,
        "tid": str,
        "cnv": str,
        "cid": str,
        "sub": str,
        "exp": int,
        "mid": NotRequired[str],
        "def": Definition,
        "md": NotRequired[str],
    },
)

_DIALOG_CLAIMS = S.Struct(
    _DialogClaims,
    aud=_ID,
    tid=_ID,
    cnv=_HASH,
    cid=_ID,
    sub=_ID,
    exp=S.Int.check(S.is_between(minimum=0, maximum=_MAX_SAFE_INTEGER)),
    mid=_ID,
    **{"def": DEFINITION},
    md=_bounded(LIMITS.metadata),
)

# --- lengths ---------------------------------------------------------------------------


def _utf8_length(text: str) -> int:
    return len(text_encode(text))


def _base64_length(size: int) -> int:
    return math.ceil(size * 4 / 3)


def _json_string(n: int) -> int:
    """A string of ``n`` characters is at most 6 bytes each in JSON, plus quotes."""
    return 6 * n + 2


_SIGNATURE_LENGTH = _base64_length(32)
"""An HS256 signature is 32 bytes."""
_HASH_LENGTH = _base64_length(32)
"""The conversation hash: base64url of a SHA-256 digest."""


def _header_json(kid: str, typ: str) -> str:
    return stringify({"alg": "HS256", "kid": kid, "typ": typ})


def _max_token_length() -> int:
    header = _utf8_length(_header_json("", _TYP_DIALOG)) + LIMITS.kid
    button = (
        _utf8_length(stringify({"aud": "", "tid": "", "cnv": "", "id": "", "val": ""}))
        - 2 * 5
        + 3 * _json_string(LIMITS.id)
        + _json_string(_HASH_LENGTH)
        + _json_string(LIMITS.button_value)
    )
    empty = {
        "aud": "",
        "tid": "",
        "cnv": "",
        "cid": "",
        "sub": "",
        "exp": 0,
        "mid": "",
        "def": 0,
        "md": "",
    }
    dialog = (
        _utf8_length(stringify(empty))
        - 2 * 7
        - 2
        + 5 * _json_string(LIMITS.id)
        + _json_string(_HASH_LENGTH)
        + len(str(_MAX_SAFE_INTEGER))
        + LIMITS.definition
        + _json_string(LIMITS.metadata)
    )
    return _base64_length(header) + 1 + _base64_length(max(button, dialog)) + 1 + _SIGNATURE_LENGTH


MAX_TOKEN_LENGTH = _max_token_length()
"""The longest token ``sign_button`` or ``sign_dialog`` can produce. A
longer value is refused before it is parsed."""


@dataclass(frozen=True)
class Button:
    """What a button token carries."""

    id: str
    value: str | None = None


def _button_claims(app_id: str, tenant_id: str, cnv: str, button: Button) -> _ButtonClaims:
    claims: _ButtonClaims = {"aud": app_id, "tid": tenant_id, "cnv": cnv, "id": button.id}
    if button.value is not None:
        claims["val"] = button.value
    return claims


def button_token_length(app_id: str, tenant_id: str, kid: str, button: Button) -> int:
    """The exact length of the token ``sign_button`` produces for
    ``button``, without signing it: the header and claims are deterministic
    JSON and the hash and signature have fixed lengths."""
    claims = _button_claims(app_id, tenant_id, "x" * _HASH_LENGTH, button)
    return (
        _base64_length(_utf8_length(_header_json(kid, _TYP_BUTTON)))
        + 1
        + _base64_length(_utf8_length(stringify(claims)))
        + 1
        + _SIGNATURE_LENGTH
    )


# --- definitions -----------------------------------------------------------------------


def _element_def(element: ModalElement) -> _ElementDef:
    if isinstance(element, Text):
        return {"_tag": "Text", "text": element.text}
    if isinstance(element, TextInput):
        text: _TextInputDef = {"_tag": "TextInput", "id": element.id, "label": element.label}
        if element.multiline:
            text["multiline"] = True
        if element.placeholder is not None:
            text["placeholder"] = element.placeholder
        if element.initial is not None:
            text["initial"] = element.initial
        if element.optional:
            text["optional"] = True
        if element.min_length is not None:
            text["minLength"] = element.min_length
        if element.max_length is not None:
            text["maxLength"] = element.max_length
        return text
    select: _SelectInputDef = {
        "_tag": "SelectInput",
        "id": element.id,
        "label": element.label,
        "options": [{"label": o.label, "value": o.value} for o in element.options],
    }
    if element.placeholder is not None:
        select["placeholder"] = element.placeholder
    if element.initial is not None:
        select["initial"] = element.initial
    if element.optional:
        select["optional"] = True
    return select


def definition_of(modal: Modal) -> Definition:
    """``modal`` without its metadata, as a token holds it; a field at its
    default is left out."""
    definition: Definition = {
        "_tag": "Modal",
        "id": modal.id,
        "title": modal.title,
        "elements": [_element_def(element) for element in modal.elements],
    }
    if modal.submit_label is not None:
        definition["submitLabel"] = modal.submit_label
    return definition


def _element_of(element: _ElementDef) -> ModalElement:
    match element["_tag"]:
        case "Text":
            return Text(text=element["text"])
        case "TextInput":
            text = element
            return TextInput(
                id=text["id"],
                label=text["label"],
                multiline=text.get("multiline", False),
                placeholder=text.get("placeholder"),
                initial=text.get("initial"),
                optional=text.get("optional", False),
                min_length=text.get("minLength"),
                max_length=text.get("maxLength"),
            )
        case "SelectInput":
            select = element
            return SelectInput(
                id=select["id"],
                label=select["label"],
                placeholder=select.get("placeholder"),
                options=tuple(
                    SelectOption(label=o["label"], value=o["value"]) for o in select["options"]
                ),
                initial=select.get("initial"),
                optional=select.get("optional", False),
            )


def modal_of(definition: Definition, metadata: str | None) -> Modal:
    """The modal a token's definition and metadata describe."""
    return Modal(
        id=definition["id"],
        title=definition["title"],
        submit_label=definition.get("submitLabel"),
        metadata=metadata,
        elements=tuple(_element_of(element) for element in definition["elements"]),
    )


# --- checks ----------------------------------------------------------------------------


def has_reserved_field(modal: Modal) -> bool:
    """Whether a field of ``modal`` uses the reserved ``effect`` id."""
    return any(not isinstance(e, Text) and e.id == RESERVED_KEY for e in modal.elements)


_is_definition = S.is_(DEFINITION)


def check_modal(modal: Modal) -> AnyReason | None:
    """Why ``modal`` cannot go in a dialog token, if it can't: a field with
    the reserved id, or more than the limits allow."""
    if has_reserved_field(modal):
        return invalid_request("reserved_field_id")
    if modal.metadata is not None and len(modal.metadata) > LIMITS.metadata:
        return too_large(None, "modal_metadata_too_long")
    definition = definition_of(modal)
    if not _is_definition(definition) or _utf8_length(stringify(definition)) > LIMITS.definition:
        return too_large(None, "modal_too_large")
    return None


def check_button(button: Button) -> AnyReason | None:
    """Why ``button`` cannot go in a button token, if it can't."""
    if len(button.id) > LIMITS.id:
        return too_large(None, "action_id_too_long")
    if button.value is not None and len(button.value) > LIMITS.button_value:
        return too_large(None, "action_data_too_long")
    return None


def validate_submission(definition: Modal, values: object) -> dict[str, str] | None:  # noqa: PLR0911
    """The values of a dialog submit, checked against the signed definition,
    or ``None`` when they don't match it.

    - Keys are the ids of the inputs. The reserved ``effect`` key is skipped.
    - Every value is a string. An optional input left empty has no key.
    - A text input is held to its ``min_length`` and ``max_length`` (default
      4,000), and a select to its options.
    """
    if not isinstance(values, dict):
        return None
    given = cast("Mapping[str, object]", values)
    fields = {e.id: e for e in definition.elements if not isinstance(e, Text)}
    if any(key != RESERVED_KEY and key not in fields for key in given):
        return None
    out: dict[str, str] = {}
    for id, field in fields.items():
        value = given.get(id)
        if value is not None and not isinstance(value, str):
            return None
        if value is None or value == "":
            if field.optional:
                continue
            return None
        if isinstance(field, TextInput):
            maximum = DEFAULT_MAX_LENGTH if field.max_length is None else field.max_length
            if not (field.min_length or 0) <= len(value) <= maximum:
                return None
        elif not any(option.value == value for option in field.options):
            return None
        out[id] = value
    return out


# --- envelope --------------------------------------------------------------------------


@dataclass(frozen=True)
class Dialog:
    """What a dialog token carries. ``conversation_id`` is the conversation
    the click came from, as Teams sent it: a submit must come from the same
    one. ``message_id`` is absent when a command opened it."""

    conversation_id: str
    modal: Modal
    message_id: str | None = None


_KID = re.compile(r"[A-Za-z0-9_-]{1,16}")

type Keys = tuple[Redacted[SecretJwk], *tuple[Redacted[SecretJwk], ...]]


class Envelope:
    """Signs and verifies button and dialog tokens; ``make`` builds it."""

    def __init__(
        self,
        *,
        app_id: str,
        tenant_id: str,
        keys: Mapping[str, HmacKey],
        signing: HmacKey,
        mac: Any,
        digest: Any,
    ) -> None:
        self._app_id = app_id
        self._tenant_id = tenant_id
        self._keys = keys
        self._signing = signing
        self._mac = mac
        self._digest = digest

    def _hash(self, conversation_id: str) -> Effect[str]:
        return self._digest.digest(
            _digest.sha256, key_bytes(base_conversation(conversation_id))
        ).map(base64_url.encode)

    def _sign(self, schema: Any, claims: Mapping[str, object], typ: str) -> Effect[str]:
        signed: Effect[Redacted[str], Any, Any] = jwt.sign(
            schema, claims, self._signing, {"typ": typ}
        )
        return signed.map(redacted_value).pipe(fx.provide_service(Mac, self._mac)).or_die()

    def _verify(
        self, schema: Any, token: object, typ: str, conversation_id: str, **policy: Any
    ) -> Effect[Mapping[str, Any] | None]:
        if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
            return fx.succeed(None)

        @fx.gen
        def run() -> Generator[Effect[Any, Any, Any], Any, Mapping[str, Any] | None]:
            unverified = yield from jwt.decode_unverified(token)
            kid = unverified.protected_header.get("kid")
            key = None if kid is None else self._keys.get(kid)
            if key is None:
                return None
            verified = yield from jwt.verify(schema, token, key, audience=self._app_id, **policy)
            if verified.protected_header.get("typ") != typ:
                return None
            claims = cast("Mapping[str, Any]", verified.claims)
            if claims["tid"] != self._tenant_id or claims["cnv"] != (
                yield from self._hash(conversation_id)
            ):
                return None
            return claims

        return run.pipe(fx.provide_service(Mac, self._mac)).catch_all(lambda _: fx.succeed(None))

    def sign_button(self, conversation_id: str, button: Button) -> Effect[str, AnyReason]:
        """Fails with the reason ``button`` is over the limits."""
        refusal = check_button(button)
        if refusal is not None:
            return fx.fail(refusal)
        return self._hash(conversation_id).flat_map(
            lambda cnv: self._sign(
                _BUTTON_CLAIMS,
                _button_claims(self._app_id, self._tenant_id, cnv, button),
                _TYP_BUTTON,
            )
        )

    def verify_button(self, token: object, *, conversation_id: str) -> Effect[Button | None]:
        """The button the token was signed for, if it was signed for this conversation."""
        return self._verify(_BUTTON_CLAIMS, token, _TYP_BUTTON, conversation_id).map(
            lambda claims: None if claims is None else Button(claims["id"], claims.get("val"))
        )

    def sign_dialog(
        self,
        dialog: Dialog,
        *,
        user_id: str,
        ttl: Duration = DEFAULT_DIALOG_TTL,
    ) -> Effect[str, AnyReason]:
        """Fails with the reason the modal or an id is refused."""
        refusal = check_modal(dialog.modal) or (
            invalid_request("id_too_long")
            if len(user_id) > LIMITS.id
            or len(dialog.message_id or "") > LIMITS.id
            or len(dialog.conversation_id) > LIMITS.id
            else None
        )
        if refusal is not None:
            return fx.fail(refusal)

        @fx.gen
        def run() -> Generator[Effect[Any, Never, Any], Any, str]:
            now = yield from current_time_millis()
            exp = math.floor((now + ttl.to_millis()) / 1000)
            claims: dict[str, object] = {
                "aud": self._app_id,
                "tid": self._tenant_id,
                "cnv": (yield from self._hash(dialog.conversation_id)),
                "cid": dialog.conversation_id,
                "sub": user_id,
                "exp": exp,
            }
            if dialog.message_id is not None:
                claims["mid"] = dialog.message_id
            claims["def"] = definition_of(dialog.modal)
            if dialog.modal.metadata is not None:
                claims["md"] = dialog.modal.metadata
            return (yield from self._sign(_DIALOG_CLAIMS, claims, _TYP_DIALOG))

        return run

    def verify_dialog(
        self, token: object, *, conversation_id: str, user_id: str
    ) -> Effect[Dialog | None]:
        """The dialog the token was signed for, if it is unexpired, for this
        user, and from exactly this conversation id."""

        def read(claims: Mapping[str, Any] | None) -> Dialog | None:
            if claims is None or claims["cid"] != conversation_id:
                return None
            return Dialog(
                conversation_id=claims["cid"],
                modal=modal_of(claims["def"], claims.get("md")),
                message_id=claims.get("mid"),
            )

        return self._verify(
            _DIALOG_CLAIMS,
            token,
            _TYP_DIALOG,
            conversation_id,
            subject=user_id,
            required_claims=["exp", "sub"],
        ).map(read)

    def token_length_of(self, button: UiButton) -> int:
        """The length of the token ``button`` would carry: ``button_token_length``
        with this envelope's app, tenant and signing key."""
        return button_token_length(
            self._app_id,
            self._tenant_id,
            cast("str", self._signing.kid),
            Button(button.id, button.value),
        )


def make(
    *, app_id: str, tenant_id: str, keys: Sequence[Redacted[SecretJwk]]
) -> Effect[Envelope, Never, Mac | Digest]:
    """Builds the envelope. The first key signs, and a token is verified with
    the key its ``kid`` names. A key without a valid ``kid``, a repeated
    ``kid`` or a key under 32 bytes is a defect."""

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, Envelope]:
        imported: dict[str, HmacKey] = {}
        first: str | None = None
        for given in keys:
            kid = redacted_value(given).get("kid")
            if kid is None or _KID.fullmatch(kid) is None:
                return (
                    yield from fx.die(
                        ValueError(
                            "Each Teams interaction key needs a kid of 1 to 16 [A-Za-z0-9_-]"
                        )
                    )
                )
            if kid in imported:
                return (
                    yield from fx.die(
                        ValueError(f'The Teams interaction key kid "{kid}" is repeated')
                    )
                )
            imported[kid] = yield from jwk.import_hmac(given, "HS256").or_die()
            first = first or kid
        if first is None:
            return (yield from fx.die(ValueError("Teams interaction keys need at least one key")))
        mac = yield from Mac()
        digest = yield from Digest()
        return Envelope(
            app_id=app_id,
            tenant_id=tenant_id,
            keys=imported,
            signing=imported[first],
            mac=mac,
            digest=digest,
        )

    return build
