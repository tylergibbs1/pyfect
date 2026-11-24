"""Port of Effect's ``packages/chat/teams/test/length.test.ts``: ``measure``
bounds what each form of the activity serialises to, and the Markdown
rendering keeps code as written and escapes math."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pyfect._json_text import stringify
from pyfect.chat.chat_ui import Action, Button, LinkButton
from pyfect.chat.teams import _length, _render


def _token_length(button: Button) -> int:
    return 20 + len(button.id) + len(button.value or "")


def _js_length(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def test_measure_bounds_each_serialised_form():
    """render / measure bounds each serialised form"""
    measure = _length.make_measure(_token_length)
    actions: Sequence[Action] = (
        Button(id="approve", label="Yes & <no>", style="danger", value="v"),
        LinkButton(label="Docs", url="https://example.com/?a=1&b=<2>"),
    )
    never: Callable[[Button], bool] = lambda _: False  # noqa: E731
    cards: list[tuple[str, Sequence[Action], Callable[[Button], bool]]] = [
        ("```\nx\n```\np\n\nq\n\nr", actions, never),
        ("> - # x", actions, never),
        ("| a | b |\n| - | - |\n| c | d |", actions, never),
        # A dialog button's label with lone surrogates.
        ("x", (Button(id="open", label="\ud800" * 20_000),), lambda _: True),
    ]
    for markdown, card_actions, opens_dialog in cards:
        card = _render.card_activity(
            markdown, card_actions, lambda button: "t" * _token_length(button), opens_dialog
        )
        assert _js_length(stringify(card)) <= measure(markdown, card_actions) + _length.R, markdown
    dollars = "$" * 10_000 + "\\$"
    assert _js_length(stringify(_render.text_activity(dollars))) <= measure(dollars, ()) + _length.R


def test_removes_only_the_opening_fence_indentation_from_code():
    """render / removes only the opening fence indentation from code"""
    [block] = _render.blocks("  ```\n    x\n  ```")
    assert block["codeSnippet"] == "  x"


def test_escapes_each_dollar_outside_code_so_teams_reads_no_math():
    """render / escapes each dollar outside code, so Teams reads no math"""
    markdown = "$x$ \\$y \\\\$z `$c$`\n```\n$$\n```\n$"
    sent = "\\$x\\$ \\$y \\\\\\$z `$c$`\n```\n$$\n```\n\\$"
    assert _render.text_activity(markdown)["text"] == sent


def test_the_message_length_is_the_edge_less_the_reservation():
    """render / the message length is the edge less the reservation"""
    assert _length.MESSAGE_LENGTH == _length.EDGE - _length.R == 44_288
