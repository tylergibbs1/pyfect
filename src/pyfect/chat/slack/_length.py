"""What a Slack message costs against its length limit."""

from __future__ import annotations

import math
from collections.abc import Sequence

from pyfect.chat.chat_ui import Action
from pyfect.chat.slack import _actions
from pyfect.chat.slack._emoji import blocks_cost

MESSAGE_LENGTH = 12_000
"""``msg_too_long``: code points of ``markdown_text`` as sent, inclusive."""


def measure(markdown: str, actions: Sequence[Action] = ()) -> int:
    """What a Markdown string and the elements beside it cost against
    ``MESSAGE_LENGTH``, as an upper bound that adds up. It is the larger of
    two counts: code points plus three for every ``<``, which may be sent as
    ``&lt;``, and Slack's 13,200 count, scaled to 12,000, of the text with
    each emoji as its shortcode plus the ``actions`` block's stored JSON."""
    return max(
        len(markdown) + 3 * markdown.count("<"),
        math.ceil((blocks_cost(markdown) + _actions.cost(_actions.elements(actions))) * 10 / 11),
    )
