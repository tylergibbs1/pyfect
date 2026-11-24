"""What a message costs against the Connector's limit, counted in UTF-16
units of the serialised activity body (``JSON.stringify(activity).length``).

Every fixed size here comes from serialising the templates in ``_render``,
so the numbers follow the renderer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pyfect._js import js_length
from pyfect._json_text import stringify
from pyfect.chat.chat_ui import Action, Button, LinkButton
from pyfect.chat.teams import _render
from pyfect.chat.teams._address import MAX_ID_LENGTH


def _size(value: object) -> int:
    return js_length(stringify(value))


def _element(value: object) -> int:
    """An element in an array, with the comma before or after it."""
    return _size(value) + 1


EDGE = 50_000
"""The size of a serialised activity body the Connector takes, in UTF-16
units. Provisional: Microsoft documents no exact number (half of the 100 KB
it documents), and this is not verified against the Connector yet."""

S = _size(_render.text_activity(""))
"""The text form with empty ``text``."""

T = _size(_render.card_activity_of([]))
"""The card form with an empty card body."""

K = _element(_render.table_cell("")) + _element(_render.COLUMN)
"""One table cell and its column definition."""

E = max(
    _element(_render.text_block("")),
    _element(_render.code_block("", "PlainText")),
    _element(_render.table([[""]])),
)
"""The largest element group a source line can add: a ``TextBlock``, a
``CodeBlock`` (with ``PlainText`` as its language), or a ``Table`` with one
row of one cell, which is also more than a new row of one cell."""

_ID = "x" * MAX_ID_LENGTH
_MAX_SAFE_INTEGER = 2**53 - 1

A = (
    _size(
        {
            "replyToId": _ID,
            "recipient": {"id": _ID},
            "entities": [
                {
                    "type": "streaminfo",
                    "streamId": _ID,
                    "streamType": "informative",
                    "streamSequence": _MAX_SAFE_INTEGER,
                },
                {
                    "type": "https://schema.org/Message",
                    "@type": "Message",
                    "@context": "https://schema.org",
                    "@id": "",
                    "additionalType": ["AIGeneratedContent"],
                },
                {"type": "targetedMessageInfo", "messageId": _ID},
            ],
        }
    )
    - 1
)
"""The members the adapter may add to an activity besides what the renderer
gives, each id at ``MAX_ID_LENGTH``: ``replyToId``, ``recipient``, and
``entities`` holding a ``streaminfo`` entity, the AI-generated label and a
``targetedMessageInfo`` entity. Ids are sent without JSON escapes."""

M_UNITS = 4_000
"""Units set aside for mention entities. Provisional: the adapter sends no
mentions in this version."""

F_UNITS = 0
"""Units set aside for file attachments: none, files are not sent in this version."""

SKELETON = max(S, T + E)
"""The fixed part of a message: the larger of the two forms with the first
element of the card. The first source line has no line break before it to
pay for its element, so ``E`` is reserved once for it."""

R = SKELETON + A + M_UNITS + F_UNITS

MESSAGE_LENGTH = EDGE - R


def _unit(code: int) -> int:  # noqa: PLR0911
    """What one UTF-16 unit of the source can cost once rendered and
    serialised. A line break pays for the element its line may start, and a
    pipe for the table cell and column it may add."""
    if code in (0x0A, 0x0D):
        return 2 + E
    if code == 0x7C:
        return 1 + K
    if code in (0x22, 0x5C):
        return 2
    if code in (0x09, 0x24):
        # A partially stripped tab in fenced code can leave three spaces.
        return 3
    if code == 0x3C:
        return 4
    if code == 0x26:
        return 5
    return 6 if code < 0x20 else 1


_COSTS = [_unit(code) for code in range(0x80)]


def weight(text: str) -> int:
    """The weight of each UTF-16 unit of ``text``: a character outside the
    BMP is two units of one each."""
    total = 0
    costs = _COSTS
    for char in text:
        code = ord(char)
        total += costs[code] if code < 0x80 else 2 if code > 0xFFFF else 1
    return total


_ROW = _element(_render.action_set([]))

type TokenLength = Callable[[Button], int]
"""The length of the signed token a button carries."""


def _action_cost(action: Action, token_length: TokenLength) -> int:
    if isinstance(action, Button):
        empty = Button(id=action.id, label="", style=action.style, value=action.value)
        return (
            _element(_render.button_action(empty, ""))
            + 2 * weight(action.label)
            + 2 * token_length(action)
            + _ROW
        )
    if isinstance(action, LinkButton):
        empty_link = LinkButton(label="", url="")
        return (
            _element(_render.link_action(empty_link))
            + weight(action.label)
            + weight(action.url)
            + _ROW
        )
    # The adapter refuses a select before it renders anything.
    return 0


def make_measure(token_length: TokenLength) -> Callable[[str, Sequence[Action]], int]:
    """The descriptor's ``measure``: the weight of each unit of the Markdown
    plus the cost of each action, where a button's cost holds its token
    twice (the action and its fallback) at ``token_length``, and each action
    pays for a whole ``ActionSet`` row. With ``R`` added it is never less
    than the size of either form of the activity."""

    def measure(markdown: str, actions: Sequence[Action] = ()) -> int:
        total = weight(markdown)
        for action in actions:
            total += _action_cost(action, token_length)
        return total

    return measure
