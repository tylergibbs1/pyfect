"""Ports of Effect's ``test/cli/Prompt.test.ts``.

Each test's docstring is the Effect test title. Prompts run on the
``MockTerminal`` port in ``_mock_terminal``; key presses queued before the
prompt starts are read in order. ``Prompt.Date`` values are aware local
datetimes where Effect has a JavaScript ``Date``.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from collections.abc import Generator
from datetime import datetime
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import layer, path, redacted, testing
from pyfect.byte_size import ByteSize
from pyfect.cli import prompt
from pyfect.cli.prompt import (
    Action,
    Beep,
    Choice,
    Event,
    Handlers,
    Input,
    NextFrame,
    ProcessInput,
    PromptTheme,
    Submit,
    make_theme,
)
from pyfect.file_system import FileInfo, FileSystem, FileType, NoopFileSystem, layer_noop
from pyfect.queue import Queue
from pyfect.terminal import Terminal, UserInput
from pyfect.testing import Services

from ._mock_terminal import display_lines, input_key, input_text
from ._mock_terminal import mock_terminal_layer as terminal_layer

ESC = "\x1b"
BELL = "\x07"

type Env = FileSystem | path.Path | Terminal | PromptTheme

test_layer = layer.merge(
    layer_noop(),
    path.layer,
    terminal_layer,
    layer.succeed(PromptTheme, make_theme(colors=True)),
)
env = testing.layer_fixture(test_layer, scope="function")


def strip_ansi(text: str) -> str:
    result = ""
    skipping = False
    for char in text:
        if skipping:
            if char.isascii() and char.isalpha():
                skipping = False
            continue
        if char == ESC:
            skipping = True
            continue
        result += char
    return result


def to_frames(lines: list[str]) -> list[str]:
    stripped = (strip_ansi(line) for line in lines)
    return [line for line in stripped if line.replace(BELL, "").strip()]


def to_raw_frames(lines: list[str]) -> list[str]:
    return [line for line in lines if strip_ansi(line).replace(BELL, "").strip()]


def find_frame(frames: list[str], text: str) -> str | None:
    return next((frame for frame in frames if text in frame), None)


def _first(frames: list[str]) -> str:
    return frames[0] if frames else ""


# --- Prompt colors -----------------------------------------------------------------


def test_disables_colors_when_no_color_is_set_on_a_tty(monkeypatch: pytest.MonkeyPatch):
    """disables colors when NO_COLOR is set on a TTY"""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    assert make_theme().colors is False


@testing.effect
def test_omits_styles_when_the_context_theme_disables_colors(env: Services[Env]):
    """omits styles when the context theme disables colors"""
    yield from input_key("enter")
    yield from prompt.run(prompt.select([Choice("Blue", "blue")], message="Choose a color")).pipe(
        fx.provide_service(PromptTheme, make_theme(colors=False))
    )
    output = "\n".join((yield from display_lines()))
    assert "Choose a color" in output
    assert re.search(rf"{ESC}\[[0-9;]*m", output) is None


# --- Prompt.Date -------------------------------------------------------------------


@testing.effect
def test_renders_two_digit_years_teen_ordinals_and_noon_meridiem_correctly(env: Services[Env]):
    """renders two-digit years, teen ordinals, and noon meridiem correctly"""
    yield from input_key("enter")
    yield from prompt.date("When", initial=datetime(2024, 1, 11, 12), date_mask="YY Do A")
    output = "\n".join((yield from display_lines()))
    assert "24 11th PM" in output


@testing.effect
def test_starts_a_fresh_typed_buffer_when_tab_advances_to_the_next_field(env: Services[Env]):
    """starts a fresh typed buffer when Tab advances to the next field"""
    yield from input_text("1")
    yield from input_key("tab")
    yield from input_text("5")
    yield from input_key("enter")
    result = yield from prompt.date("When", initial=datetime(2024, 1, 1, 12), date_mask="MM-DD")
    assert result == datetime(2024, 1, 5, 12).astimezone()


@testing.effect
def test_starts_a_fresh_typed_buffer_when_tab_wraps_to_the_first_field(env: Services[Env]):
    """starts a fresh typed buffer when Tab wraps to the first field"""
    yield from input_key("tab")
    yield from input_text("1")
    yield from input_key("tab")
    yield from input_text("5")
    yield from input_key("enter")
    result = yield from prompt.date("When", initial=datetime(2024, 1, 1, 12), date_mask="DD-MM")
    assert result == datetime(2024, 1, 5, 12).astimezone()


@testing.effect
def test_accumulates_multiple_digits_while_staying_in_the_same_field(env: Services[Env]):
    """accumulates multiple digits while staying in the same field"""
    yield from input_text("15")
    yield from input_key("enter")
    result = yield from prompt.date("When", initial=datetime(2024, 1, 1, 12), date_mask="DD")
    assert result == datetime(2024, 1, 15, 12).astimezone()


@testing.effect
def test_starts_a_fresh_typed_buffer_when_tab_wraps_a_single_editable_field(env: Services[Env]):
    """starts a fresh typed buffer when Tab wraps a single editable field"""
    yield from input_text("1")
    yield from input_key("tab")
    yield from input_text("5")
    yield from input_key("enter")
    result = yield from prompt.date("When", initial=datetime(2024, 1, 1, 12), date_mask="DD")
    assert result == datetime(2024, 1, 5, 12).astimezone()


# --- Prompt.succeed / Prompt.all -------------------------------------------------------


@testing.effect
def test_does_not_acquire_terminal_input(env: Services[Env]):
    """does not acquire terminal input"""
    terminal = yield from Terminal()
    acquisitions = 0

    def count() -> None:
        nonlocal acquisitions
        acquisitions += 1

    counting = dataclasses.replace(
        terminal, read_input=fx.sync(count).flat_map(lambda _: terminal.read_input)
    )
    result = yield from prompt.run(prompt.succeed("x")).pipe(fx.provide_service(Terminal, counting))
    assert result == "x"
    assert acquisitions == 0


@testing.effect
def test_supports_an_empty_record(env: Services[Env]):
    """supports an empty record"""
    result = yield from prompt.all(dict[str, prompt.Prompt[int]]())
    assert result == {}


@testing.effect
def test_supports_a_non_array_iterable(env: Services[Env]):
    """supports a non-array iterable"""
    result = yield from prompt.all(p for p in (prompt.succeed(1),))
    assert result == [1]


# --- Prompt.Int / Prompt.Number ----------------------------------------------------------


@testing.effect
def test_submits_the_default_value(env: Services[Env]):
    """submits the default value"""
    yield from input_key("enter")
    result = yield from prompt.integer("Count", default=42)
    assert result == 42


@testing.effect
def test_int_starts_from_the_default_value_so_it_can_be_edited(env: Services[Env]):
    """starts from the default value so it can be edited"""
    yield from input_text("2")
    yield from input_key("enter")
    result = yield from prompt.integer("Count", default=4)
    assert result == 42


@testing.effect
def test_clears_the_default_value_on_ctrl_u(env: Services[Env]):
    """clears the default value on ctrl-u"""
    yield from input_key("u", ctrl=True)
    yield from input_text("7")
    yield from input_key("enter")
    result = yield from prompt.integer("Count", default=42)
    assert result == 7


@testing.effect
def test_preserves_a_leading_zero_in_the_fractional_part(env: Services[Env]):
    """preserves a leading zero in the fractional part"""
    yield from input_text("0.05")
    yield from input_key("enter")
    value = yield from prompt.number("Rate")
    assert value == 0.05


@testing.effect
def test_renders_appended_input_without_literal_parsed(env: Services[Env]):
    """renders appended input without literal parsed"""
    yield from input_text("12.5")
    yield from input_key("enter")
    result = yield from prompt.number("Rate")
    assert result == 12.5
    rendered = "\n".join(to_frames((yield from display_lines())))
    assert "12.5" in rendered
    assert "parsed" not in rendered


@testing.effect
def test_number_clears_the_current_input_on_ctrl_u(env: Services[Env]):
    """clears the current input on ctrl-u"""
    yield from input_text("12.5")
    yield from input_key("u", ctrl=True)
    yield from input_text("7.25")
    yield from input_key("enter")
    result = yield from prompt.number("Rate")
    assert result == 7.25


# --- Prompt.String -------------------------------------------------------------------


@testing.effect
def test_renders_the_default_prompt_theme(env: Services[Env]):
    """renders the default prompt theme"""
    yield from input_key("enter")
    yield from prompt.string("Name")
    frames = to_frames((yield from display_lines()))
    assert "? Name" in _first(frames)


@testing.effect
def test_renders_the_prompt_theme_from_context(env: Services[Env]):
    """renders the prompt theme from context"""
    yield from input_key("enter")
    theme = make_theme(prefix="!", pointer_small=">", tick="+", ellipsis="~")
    yield from prompt.run(prompt.string("Name")).pipe(fx.provide_service(PromptTheme, theme))
    frames = to_frames((yield from display_lines()))
    assert "! Name >" in _first(frames)
    assert "+ Name ~" in frames[-1]


@testing.effect
def test_renders_theme_colors_from_context_with_per_prompt_overrides(env: Services[Env]):
    """renders theme colors from context with per-prompt overrides"""
    yield from input_text("A")
    yield from input_key("enter")
    theme = make_theme(
        colors=True,
        primary_color=f"{ESC}[31m",
        muted_color=f"{ESC}[34m",
        success_color=f"{ESC}[33m",
        submitted_color=f"{ESC}[36m",
    )
    yield from prompt.run(prompt.string("Name", theme={"primary_color": f"{ESC}[35m"})).pipe(
        fx.provide_service(PromptTheme, theme)
    )
    output = "\n".join(to_raw_frames((yield from display_lines())))
    assert f"{ESC}[35m?" in output
    assert f"{ESC}[34m\u203a" in output
    assert f"{ESC}[33m✔" in output
    assert f"{ESC}[36mA" in output
    assert f"{ESC}[31m?" not in output


@testing.effect
def test_renders_validation_errors_with_the_theme_error_color(env: Services[Env]):
    """renders validation errors with the theme error color"""
    yield from input_text("bad")
    yield from input_key("enter")
    yield from input_key("u", ctrl=True)
    yield from input_text("ok")
    yield from input_key("enter")

    def validate(value: str) -> fx.Effect[str, str]:
        return fx.fail("Try again") if value == "bad" else fx.succeed(value)

    yield from prompt.string("Name", validate=validate, theme={"error_color": f"{ESC}[35m"})
    output = "\n".join(to_raw_frames((yield from display_lines())))
    assert f"{ESC}[35m\u203a" in output
    assert f"{ESC}[35mbad" in output
    assert f"{ESC}[31m\u203a" not in output


@testing.effect
def test_omits_spacing_for_empty_theme_symbols(env: Services[Env]):
    """omits spacing for empty theme symbols"""
    yield from input_key("enter")
    yield from prompt.string("Name", theme={"prefix": "", "pointer_small": ""})
    frames = to_frames((yield from display_lines()))
    assert frames[0] == "Name"


@testing.effect
def test_string_starts_from_the_default_value_so_it_can_be_edited(env: Services[Env]):
    """starts from the default value so it can be edited"""
    yield from input_text(" Doe")
    yield from input_key("enter")
    result = yield from prompt.string("Name", default="Jane")
    assert result == "Jane Doe"


@testing.effect
def test_string_clears_the_current_input_on_ctrl_u(env: Services[Env]):
    """clears the current input on ctrl-u"""
    yield from input_text(" Doe")
    yield from input_key("u", ctrl=True)
    yield from input_text("John")
    yield from input_key("enter")
    result = yield from prompt.string("Name", default="Jane")
    assert result == "John"


@testing.effect
def test_moves_the_cursor_to_the_beginning_on_ctrl_a(env: Services[Env]):
    """moves the cursor to the beginning on ctrl-a"""
    yield from input_text(" Doe")
    yield from input_key("a", ctrl=True)
    yield from input_text("Dr. ")
    yield from input_key("enter")
    result = yield from prompt.string("Name", default="Jane")
    assert result == "Dr. Jane Doe"


@testing.effect
def test_moves_the_cursor_to_the_end_on_ctrl_e(env: Services[Env]):
    """moves the cursor to the end on ctrl-e"""
    yield from input_text("Jane")
    yield from input_key("left")
    yield from input_key("left")
    yield from input_key("e", ctrl=True)
    yield from input_text(" Doe")
    yield from input_key("enter")
    result = yield from prompt.string("Name")
    assert result == "Jane Doe"


@testing.effect
def test_does_not_insert_characters_for_unsupported_ctrl_key_combinations(env: Services[Env]):
    """does not insert characters for unsupported ctrl key combinations"""
    yield from input_text("Ja")
    yield from input_key("l", ctrl=True)
    yield from input_text("ne")
    yield from input_key("enter")
    result = yield from prompt.string("Name")
    assert result == "Jane"


@testing.effect
def test_does_not_render_or_submit_the_cleared_default_value(env: Services[Env]):
    """does not render or submit the cleared default value"""
    yield from input_key("u", ctrl=True)
    yield from input_key("enter")
    result = yield from prompt.string("Name", default="Jane")
    assert result == ""
    frames = to_frames((yield from display_lines()))
    assert frames
    assert "Jane" not in frames[-1]


# --- Prompt.Select -------------------------------------------------------------------


@testing.effect
def test_select_renders_only_the_choice_list_when_message_is_omitted(env: Services[Env]):
    """renders only the choice list when message is omitted"""
    yield from input_key("down")
    yield from input_key("enter")
    result = yield from prompt.select([Choice("First", "first"), Choice("Second", "second")])
    assert result == "second"
    output = yield from display_lines()
    assert to_frames(output) == [
        "\u276f First \n  Second ",
        "  First \n\u276f Second ",
        "✔ Second\n",
    ]
    assert to_raw_frames(output)[1].startswith(f"{ESC}[2K{ESC}[1A{ESC}[2K{ESC}[G")


@testing.effect
def test_keeps_the_header_when_message_is_empty(env: Services[Env]):
    """keeps the header when message is empty"""
    yield from input_key("enter")
    yield from prompt.select([Choice("First", "first")], message="")
    frames = to_frames((yield from display_lines()))
    assert frames[0].split("\n")[0] == "?  \u203a "


@testing.effect
def test_renders_a_per_prompt_theme_across_redraws(env: Services[Env]):
    """renders a per-prompt theme across redraws"""
    yield from input_key("down")
    yield from input_key("enter")
    result = yield from prompt.select(
        [Choice("First", "first", "one"), Choice("Second", "second", "two")],
        message="Pick item",
        theme={"prefix": "!", "pointer": ">", "description_separator": ": "},
    )
    assert result == "second"
    frames = to_frames((yield from display_lines()))
    assert len([frame for frame in frames if "! Pick item" in frame]) == 2
    assert any("> Second : two" in frame for frame in frames)


@testing.effect
def test_renders_selection_colors_from_the_prompt_theme(env: Services[Env]):
    """renders selection colors from the prompt theme"""
    yield from input_key("enter")
    yield from prompt.select(
        [Choice("First", "first", "one")],
        message="Pick item",
        theme={
            "primary_color": f"{ESC}[35m",
            "muted_color": f"{ESC}[34m",
            "success_color": f"{ESC}[33m",
            "submitted_color": f"{ESC}[36m",
        },
    )
    output = "\n".join(to_raw_frames((yield from display_lines())))
    assert f"{ESC}[35m\u276f" in output
    assert f"{ESC}[34m- one" in output
    assert f"{ESC}[33m✔" in output
    assert f"{ESC}[36mFirst" in output


@testing.effect
def test_keeps_title_and_description_separated_when_the_theme_separator_is_empty(
    env: Services[Env],
):
    """keeps title and description separated when the theme separator is empty"""
    yield from input_key("enter")
    yield from prompt.select(
        [Choice("First", "first", "one")],
        message="Pick item",
        theme={"description_separator": "", "muted_color": f"{ESC}[34m"},
    )
    output = yield from display_lines()
    frames = to_frames(output)
    assert any("First one" in frame for frame in frames)
    assert not any("Firstone" in frame for frame in frames)
    assert any(f"{ESC}[34mone{ESC}[0m" in frame for frame in to_raw_frames(output))


@testing.effect
def test_select_aligns_choices_when_paging_arrows_have_different_widths(env: Services[Env]):
    """aligns choices when paging arrows have different widths"""
    yield from input_key("down")
    yield from input_key("down")
    yield from input_key("enter")
    yield from prompt.select(
        [Choice("Alpha", "alpha"), Choice("Beta", "beta"), Choice("Gamma", "gamma")],
        message="Pick item",
        max_per_page=2,
        theme={"arrow_up": "", "arrow_down": "vvv"},
    )
    frames = to_frames((yield from display_lines()))
    assert any("\u276f   Alpha" in frame and "vvv Beta" in frame for frame in frames)
    assert any("    Beta" in frame and "\u276f   Gamma" in frame for frame in frames)


# --- Prompt.Password -----------------------------------------------------------------


@testing.effect
def test_renders_the_password_mask_from_the_prompt_theme(env: Services[Env]):
    """renders the password mask from the prompt theme"""
    yield from input_text("abc")
    yield from input_key("enter")
    yield from prompt.run(prompt.password("Password")).pipe(
        fx.provide_service(PromptTheme, make_theme(password_mask="•"))
    )
    frames = to_frames((yield from display_lines()))
    assert any("•••" in frame for frame in frames)
    assert not any("***" in frame for frame in frames)


@testing.effect
def test_keeps_cursor_movement_aligned_with_a_multi_character_password_mask(env: Services[Env]):
    """keeps cursor movement aligned with a multi-character password mask"""
    yield from input_text("abc")
    yield from input_key("left")
    yield from input_key("enter")
    yield from prompt.password("Password", theme={"password_mask": "**"})
    frames = to_raw_frames((yield from display_lines()))
    assert any("******" in frame and frame.endswith(f"{ESC}[2D") for frame in frames)


@testing.effect
def test_password_starts_from_the_default_value_so_it_can_be_edited(env: Services[Env]):
    """starts from the default value so it can be edited"""
    yield from input_text("123")
    yield from input_key("enter")
    result = yield from prompt.password("Password", default="secret")
    assert redacted.value(result) == "secret123"


@testing.effect
def test_does_not_submit_the_cleared_default_value(env: Services[Env]):
    """does not submit the cleared default value"""
    yield from input_key("u", ctrl=True)
    yield from input_key("enter")
    result = yield from prompt.password("Password", default="secret")
    assert redacted.value(result) == ""


# --- Prompt.Toggle -------------------------------------------------------------------


@testing.effect
def test_renders_the_separator_from_the_prompt_theme(env: Services[Env]):
    """renders the separator from the prompt theme"""
    yield from input_key("enter")
    yield from prompt.toggle("Enabled", theme={"toggle_separator": "|"})
    frames = to_frames((yield from display_lines()))
    assert any("on | off" in frame for frame in frames)
    assert not any("on / off" in frame for frame in frames)


@testing.effect
def test_keeps_labels_separated_when_the_theme_separator_is_empty(env: Services[Env]):
    """keeps labels separated when the theme separator is empty"""
    yield from input_key("enter")
    yield from prompt.toggle("Enabled", theme={"toggle_separator": ""})
    frames = to_frames((yield from display_lines()))
    assert any("on off" in frame for frame in frames)
    assert not any("onoff" in frame for frame in frames)


# --- Prompt.AutoComplete ---------------------------------------------------------------

_ALPHA_BETA_DELTA = [Choice("Alpha", "alpha"), Choice("Beta", "beta"), Choice("Delta", "delta")]


@testing.effect
def test_filters_choices_as_you_type(env: Services[Env]):
    """filters choices as you type"""
    choices = [Choice("Apple", "apple"), Choice("Banana", "banana"), Choice("Cherry", "cherry")]
    yield from input_text("ban")
    yield from input_key("enter")
    result = yield from prompt.auto_complete("Pick fruit", choices)
    assert result == "banana"
    frame = find_frame(to_frames((yield from display_lines())), "[filter: ban]")
    assert frame is not None
    assert "Banana" in frame
    assert "Apple" not in frame


@testing.effect
def test_auto_complete_removes_the_last_character_on_backspace(env: Services[Env]):
    """removes the last character on backspace"""
    yield from input_text("al")
    yield from input_key("backspace")
    yield from input_key("enter")
    result = yield from prompt.auto_complete("Pick item", _ALPHA_BETA_DELTA)
    assert result == "alpha"
    frames = to_frames((yield from display_lines()))
    narrowed = find_frame(frames, "[filter: al]")
    expanded = find_frame(frames, "[filter: a]")
    assert narrowed is not None
    assert expanded is not None
    assert "Beta" not in narrowed
    assert "Beta" in expanded


@testing.effect
def test_clears_the_filter_input_on_ctrl_u(env: Services[Env]):
    """clears the filter input on ctrl-u"""
    yield from input_text("al")
    yield from input_key("u", ctrl=True)
    yield from input_key("enter")
    result = yield from prompt.auto_complete("Pick item", _ALPHA_BETA_DELTA)
    assert result == "alpha"
    frames = to_frames((yield from display_lines()))
    narrowed = find_frame(frames, "[filter: al]")
    cleared = find_frame(frames, "[filter: type to filter]")
    assert narrowed is not None
    assert cleared is not None
    assert "Beta" not in narrowed
    assert "Beta" in cleared


@testing.effect
def test_renders_empty_message_and_beeps_on_submit_with_no_matches(env: Services[Env]):
    """renders empty message and beeps on submit with no matches"""
    yield from input_text("zzz")
    yield from input_key("enter")
    for _ in range(3):
        yield from input_key("backspace")
    yield from input_key("enter")
    result = yield from prompt.auto_complete(
        "Pick pet", [Choice("Cat", "cat"), Choice("Dog", "dog")]
    )
    assert result == "cat"
    output = yield from display_lines()
    assert any(BELL in line for line in output)
    assert find_frame(to_frames(output), "No matches") is not None


@testing.effect
def test_beeps_when_submitting_a_disabled_choice(env: Services[Env]):
    """beeps when submitting a disabled choice"""
    yield from input_key("enter")
    yield from input_key("down")
    yield from input_key("enter")
    result = yield from prompt.auto_complete(
        "Pick mode", [Choice("Slow", "slow", disabled=True), Choice("Fast", "fast")]
    )
    assert result == "fast"
    assert any(BELL in line for line in (yield from display_lines()))


@testing.effect
def test_renders_empty_message_with_no_choices(env: Services[Env]):
    """renders empty message with no choices"""
    yield from input_key("c", ctrl=True)
    exit = yield from prompt.run(prompt.auto_complete("Pick option", list[Choice[str]]())).exit()
    assert isinstance(exit, fx.Failure)
    assert find_frame(to_frames((yield from display_lines())), "No matches") is not None


_BRANCHES = ["feat/jira-fetch-tool", "main", "feat/worktree-tool"]


@testing.effect
def test_keeps_j_and_k_in_the_filter_query_instead_of_moving_the_cursor(env: Services[Env]):
    """keeps `j` and `k` in the filter query instead of moving the cursor"""
    yield from input_text("jira")
    yield from input_key("enter")
    result = yield from prompt.auto_complete("Pick a branch", [Choice(b, b) for b in _BRANCHES])
    assert result == "feat/jira-fetch-tool"
    frame = find_frame(to_frames((yield from display_lines())), "[filter: jira]")
    assert frame is not None
    assert "feat/jira-fetch-tool" in frame
    assert "main" not in frame


@testing.effect
def test_filters_a_query_that_merely_contains_a_k(env: Services[Env]):
    """filters a query that merely contains a `k`"""
    branches = ["main", "feat/jira-fetch-tool", "feat/worktree-tool"]
    yield from input_text("worktree")
    yield from input_key("enter")
    result = yield from prompt.auto_complete("Pick a branch", [Choice(b, b) for b in branches])
    assert result == "feat/worktree-tool"
    frame = find_frame(to_frames((yield from display_lines())), "[filter: worktree]")
    assert frame is not None
    assert "feat/worktree-tool" in frame
    assert "feat/jira-fetch-tool" not in frame


@testing.effect
def test_auto_complete_moves_the_cursor_with_ctrl_n_and_ctrl_p(env: Services[Env]):
    """moves the cursor with ctrl-n and ctrl-p"""
    yield from input_key("n", ctrl=True)
    yield from input_key("n", ctrl=True)
    yield from input_key("p", ctrl=True)
    yield from input_key("enter")
    result = yield from prompt.auto_complete("Pick item", _ALPHA_BETA_DELTA)
    assert result == "beta"


@testing.effect
def test_auto_complete_moves_the_cursor_up_with_ctrl_k(env: Services[Env]):
    """moves the cursor up with ctrl-k"""
    yield from input_key("down")
    yield from input_key("down")
    yield from input_key("k", ctrl=True)
    yield from input_key("enter")
    result = yield from prompt.auto_complete("Pick item", _ALPHA_BETA_DELTA)
    assert result == "beta"


# --- Prompt.File ---------------------------------------------------------------------


def _info(kind: FileType) -> FileInfo:
    return FileInfo(
        type=kind,
        mtime=None,
        atime=None,
        birthtime=None,
        dev=0,
        ino=None,
        mode=0,
        nlink=None,
        uid=None,
        gid=None,
        rdev=None,
        size=ByteSize(0),
        blksize=None,
        blocks=None,
    )


class _Workspace(NoopFileSystem):
    files: tuple[str, ...] = ("alpha.txt", "banana.txt", "basket.txt")

    def exists(self, path: str):
        return fx.succeed(True)

    def read_directory(self, path: str, *, recursive: bool = False):
        return fx.succeed(list(self.files) if path == "/workspace" else [])

    def stat(self, path: str):
        return fx.succeed(_info("File" if path.endswith(".txt") else "Directory"))


class _JkWorkspace(_Workspace):
    files = ("jest.config.ts", "package.json", "readme.md")

    def stat(self, path: str):
        return fx.succeed(_info("File"))


def _file_env(fs: NoopFileSystem):
    return layer.merge(layer.succeed(FileSystem, fs), path.layer, terminal_layer)


file_env = testing.layer_fixture(_file_env(_Workspace()), scope="function")
jk_file_env = testing.layer_fixture(_file_env(_JkWorkspace()), scope="function")

type FileEnv = FileSystem | path.Path | Terminal


@testing.effect
def test_file_starts_from_the_default_value_so_it_can_be_submitted(file_env: Services[FileEnv]):
    """starts from the default value so it can be submitted"""
    yield from input_key("enter")
    result = yield from prompt.file(message="Pick file", default="/workspace/banana.txt")
    assert result == "/workspace/banana.txt"


@testing.effect
def test_filters_files_as_you_type(file_env: Services[FileEnv]):
    """filters files as you type"""
    yield from input_text("ban")
    yield from input_key("enter")
    result = yield from prompt.file(message="Pick file", starting_path="/workspace")
    assert result == "/workspace/banana.txt"
    frame = find_frame(to_frames((yield from display_lines())), "[filter: ban]")
    assert frame is not None
    assert "banana.txt" in frame
    assert "alpha.txt" not in frame
    assert "basket.txt" not in frame


@testing.effect
def test_file_removes_the_last_character_on_backspace(file_env: Services[FileEnv]):
    """removes the last character on backspace"""
    yield from input_text("ban")
    yield from input_key("backspace")
    yield from input_key("enter")
    result = yield from prompt.file(message="Pick file", starting_path="/workspace")
    assert result == "/workspace/banana.txt"
    frames = to_frames((yield from display_lines()))
    narrowed = find_frame(frames, "[filter: ban]")
    expanded = find_frame(frames, "[filter: ba]")
    assert narrowed is not None
    assert expanded is not None
    assert "basket.txt" not in narrowed
    assert "basket.txt" in expanded


@testing.effect
def test_keeps_j_in_the_filter_query_instead_of_moving_the_cursor(jk_file_env: Services[FileEnv]):
    """keeps `j` in the filter query instead of moving the cursor"""
    yield from input_text("jest")
    yield from input_key("enter")
    result = yield from prompt.file(message="Pick file", starting_path="/workspace")
    assert result == "/workspace/jest.config.ts"
    frame = find_frame(to_frames((yield from display_lines())), "[filter: jest]")
    assert frame is not None
    assert "jest.config.ts" in frame
    assert "readme.md" not in frame


@testing.effect
def test_keeps_k_in_the_filter_query_instead_of_moving_the_cursor(jk_file_env: Services[FileEnv]):
    """keeps `k` in the filter query instead of moving the cursor"""
    yield from input_text("package")
    yield from input_key("enter")
    result = yield from prompt.file(message="Pick file", starting_path="/workspace")
    assert result == "/workspace/package.json"
    frame = find_frame(to_frames((yield from display_lines())), "[filter: package]")
    assert frame is not None
    assert "package.json" in frame
    assert "readme.md" not in frame


@testing.effect
def test_file_moves_the_cursor_with_ctrl_n_and_ctrl_p(file_env: Services[FileEnv]):
    """moves the cursor with ctrl-n and ctrl-p"""
    yield from input_key("n", ctrl=True)
    yield from input_key("n", ctrl=True)
    yield from input_key("p", ctrl=True)
    yield from input_key("enter")
    result = yield from prompt.file(message="Pick file", starting_path="/workspace")
    assert result == "/workspace/alpha.txt"


@testing.effect
def test_file_moves_the_cursor_up_with_ctrl_k(file_env: Services[FileEnv]):
    """moves the cursor up with ctrl-k"""
    yield from input_key("down")
    yield from input_key("down")
    yield from input_key("k", ctrl=True)
    yield from input_key("enter")
    result = yield from prompt.file(message="Pick file", starting_path="/workspace")
    assert result == "/workspace/alpha.txt"


# --- Prompt.MultiSelect ----------------------------------------------------------------

_CLEAR_CHOICES = f"{ESC}[2K{ESC}[1A" * 3 + f"{ESC}[2K{ESC}[G"
_CLEAR_ERROR = f"{ESC}[1B{ESC}[2K{ESC}[1A{ESC}[2K{ESC}[G"


@testing.effect
def test_multi_select_renders_only_the_choice_list_when_message_is_omitted(env: Services[Env]):
    """renders only the choice list when message is omitted"""
    yield from input_key("space")
    yield from input_key("enter")
    result = yield from prompt.multi_select([Choice("First", "first"), Choice("Second", "second")])
    assert result == ["first", "second"]
    output = yield from display_lines()
    assert to_frames(output) == [
        "  Select All\n  Inverse Selection\n  ☐ First \n  ☐ Second ",
        "  Select None\n  Inverse Selection\n  ☒ First \n  ☒ Second ",
        "✔ First, Second\n",
    ]
    assert to_raw_frames(output)[1].startswith(_CLEAR_CHOICES)


@testing.effect
def test_clears_validation_errors_without_a_message(env: Services[Env]):
    """clears validation errors without a message"""
    yield from input_key("enter")
    yield from input_key("space")
    yield from input_key("enter")
    result = yield from prompt.multi_select(
        [Choice("First", "first"), Choice("Second", "second")], min=1
    )
    assert result == ["first", "second"]
    output = yield from display_lines()
    frames = to_frames(output)
    assert frames[1].endswith("\n\u276f At least 1 are required")
    assert frames[-1] == "✔ First, Second\n"
    raw = to_raw_frames(output)
    assert raw[2].startswith(_CLEAR_ERROR + _CLEAR_CHOICES)
    assert raw[3].startswith(_CLEAR_ERROR + _CLEAR_CHOICES)


@testing.effect
def test_renders_paging_and_checkbox_symbols_from_the_prompt_theme(env: Services[Env]):
    """renders paging and checkbox symbols from the prompt theme"""
    yield from input_key("down")
    yield from input_key("down")
    yield from input_key("space")
    yield from input_key("enter")
    value = yield from prompt.multi_select(
        [Choice("Alpha", "alpha"), Choice("Beta", "beta")],
        message="Pick items",
        max_per_page=3,
        theme={"arrow_down": "v", "checkbox_on": "[x]", "checkbox_off": "[ ]"},
    )
    assert value == ["alpha"]
    frames = to_frames((yield from display_lines()))
    assert any("v [ ] Alpha" in frame for frame in frames)
    assert any("[x] Alpha" in frame for frame in frames)


@testing.effect
def test_aligns_choices_when_checkbox_symbols_have_different_widths(env: Services[Env]):
    """aligns choices when checkbox symbols have different widths"""
    yield from input_key("enter")
    yield from prompt.multi_select(
        [Choice("Alpha", "alpha", selected=True), Choice("Beta", "beta")],
        message="Pick items",
        theme={"checkbox_on": "[x]", "checkbox_off": ""},
    )
    frames = to_frames((yield from display_lines()))
    frame = next(f for f in frames if "[x] Alpha" in f and "Beta" in f)
    alpha = next(line for line in frame.split("\n") if "Alpha" in line)
    beta = next(line for line in frame.split("\n") if "Beta" in line)
    assert alpha.index("Alpha") == beta.index("Beta")


@testing.effect
def test_does_not_allow_a_disabled_multi_select_choice_to_be_selected(env: Services[Env]):
    """does not allow a disabled multi-select choice to be selected"""
    yield from input_key("down")
    yield from input_key("down")
    yield from input_key("space")
    yield from input_key("enter")
    value = yield from prompt.multi_select(
        [Choice("Unavailable", "unavailable", disabled=True)], message="Pick items"
    )
    assert value == []
    assert any(BELL in line for line in (yield from display_lines()))


_AVAILABLE = [Choice("Available", "available"), Choice("Unavailable", "unavailable", disabled=True)]


@testing.effect
def test_does_not_select_disabled_choices_when_selecting_all(env: Services[Env]):
    """does not select disabled choices when selecting all"""
    yield from input_key("space")
    yield from input_key("enter")
    value = yield from prompt.multi_select(_AVAILABLE, message="Pick items")
    assert value == ["available"]
    assert find_frame(to_frames((yield from display_lines())), "Select None") is not None


@testing.effect
def test_does_not_select_disabled_choices_when_inverting_the_selection(env: Services[Env]):
    """does not select disabled choices when inverting the selection"""
    yield from input_key("down")
    yield from input_key("space")
    yield from input_key("enter")
    value = yield from prompt.multi_select(_AVAILABLE, message="Pick items")
    assert value == ["available"]


@testing.effect
def test_ignores_disabled_preselected_choices_when_validating_and_submitting(env: Services[Env]):
    """ignores disabled preselected choices when validating and submitting"""
    yield from input_key("enter")
    value = yield from prompt.multi_select(
        [
            Choice("Available", "available", selected=True),
            Choice("Unavailable", "unavailable", disabled=True, selected=True),
        ],
        message="Pick items",
        max=1,
    )
    assert value == ["available"]
    output = yield from display_lines()
    initial = find_frame(to_frames(output), "Unavailable")
    assert initial is not None
    assert "☐ Unavailable" in initial
    raw_initial = find_frame(to_raw_frames(output), "Unavailable")
    assert raw_initial is not None
    assert f"{ESC}[9m{ESC}[90mUnavailable" in raw_initial


@testing.effect
def test_underlines_the_active_label(env: Services[Env]):
    """underlines the active label"""
    fiber = yield from prompt.run(
        prompt.multi_select(
            [Choice("Alpha", "alpha"), Choice("Beta", "beta"), Choice("Gamma", "gamma")],
            message="Pick items",
        )
    ).fork()
    yield from fx.yield_now()
    yield from input_key("down")
    yield from input_key("down")
    yield from input_key("down")
    yield from fx.yield_now()
    frames = to_raw_frames((yield from display_lines()))
    highlighted = next((frame for frame in reversed(frames) if "Beta" in frame), None)
    assert highlighted is not None
    assert f"{ESC}[4m{ESC}[96mBeta{ESC}[0m" in highlighted
    yield from input_key("enter")
    result = yield from fiber.join()
    assert result == []


# --- Prompt.Custom -------------------------------------------------------------------


def _custom_transition(transition: type[NextFrame[Any]] | type[Submit[Any]]):
    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        rendering = yield from fx.Deferred[None, Never].make()
        resume = yield from fx.Deferred[None, Never].make()
        calls: list[str] = []
        clear = f"{ESC}[2K\r"

        def name(action: Action[int, int]) -> str:
            return type(action).__name__

        def render(state: int, action: Action[int, int]):
            def run():
                calls.append(f"render {state} {name(action)}")
                if isinstance(action, transition) and (state > 0 or isinstance(action, Submit)):
                    yield from rendering.succeed(None)
                    yield from resume.wait()
                if isinstance(action, Submit):
                    return f"Done {state}"
                return BELL if isinstance(action, Beep) else f"Frame {state}"

            return fx.gen(run)

        def clear_frame(state: int, action: Action[int, int]):
            def run() -> str:
                calls.append(f"clear {state} {name(action)}")
                return clear

            return fx.sync(run)

        def process(input: UserInput, state: int) -> fx.Effect[Action[int, int]]:
            if input.key.name == "q":
                return fx.succeed(Submit(42))
            if input.key.name == "b":
                return fx.succeed(Beep())
            return fx.succeed(NextFrame(state + 1))

        custom = prompt.custom(0, Handlers(render, process, clear_frame))
        next_frame = transition is NextFrame
        if next_frame:
            yield from input_key("enter")
            yield from input_key("b")
        yield from input_key("q")
        fiber = yield from prompt.run(custom).fork()
        yield from rendering.wait()

        assert (yield from display_lines()) == ["Frame 0"]
        tag = transition.__name__
        assert calls == [
            "render 0 NextFrame",
            f"clear 0 {tag}",
            f"render {1 if next_frame else 0} {tag}",
        ]
        yield from resume.succeed(None)
        assert (yield from fiber.join()) == 42
        expected = (
            ["Frame 0", f"{clear}Frame 1", BELL, f"{clear}Done 1", f"{ESC}[?25h"]
            if next_frame
            else ["Frame 0", f"{clear}Done 0", f"{ESC}[?25h"]
        )
        assert (yield from display_lines()) == expected

    return body()


@testing.effect
def test_keeps_the_previous_frame_visible_while_rendering_next_frame(env: Services[Env]):
    """keeps the previous frame visible while rendering NextFrame"""
    yield from _custom_transition(NextFrame)


@testing.effect
def test_keeps_the_previous_frame_visible_while_rendering_submit(env: Services[Env]):
    """keeps the previous frame visible while rendering Submit"""
    yield from _custom_transition(Submit)


@dataclasses.dataclass(frozen=True)
class _Count:
    count: int


@testing.effect
def test_receive_handles_events_from_external_dequeue(env: Services[Env]):
    """receive handles events from external dequeue"""
    events = yield from Queue[str, Never].unbounded()

    def render(state: _Count, action: Action[_Count, int]) -> fx.Effect[str]:
        return fx.succeed(f"Count: {state.count}")

    def process(input: ProcessInput[str], state: _Count) -> fx.Effect[Action[_Count, int]]:
        match input:
            case Input():
                return fx.succeed(Submit(state.count))
            case Event(value):
                return fx.succeed(NextFrame(_Count(state.count + (1 if value == "tick" else 0))))

    custom = prompt.custom(
        _Count(0), events, Handlers(render, process, lambda _s, _a: fx.succeed(""))
    )
    fiber = yield from prompt.run(custom).fork()
    yield from fx.yield_now()
    for value in ("tick", "tock", "tick"):
        yield from events.offer(value)
        yield from fx.yield_now()
    yield from input_key("enter")
    assert (yield from fiber.join()) == 2


@testing.effect
def test_falls_back_to_process_when_no_events_are_pending(env: Services[Env]):
    """falls back to process when no events are pending"""
    events = yield from Queue[str, Never].unbounded()

    def process(input: ProcessInput[str], state: int) -> fx.Effect[Action[int, int]]:
        match input:
            case Input():
                following = state + 1
                return fx.succeed(Submit(following) if following >= 3 else NextFrame(following))
            case Event():
                return fx.succeed(NextFrame(state))

    custom = prompt.custom(
        0,
        events,
        Handlers(
            lambda state, _: fx.succeed(f"Keys: {state}"),
            process,
            lambda _s, _a: fx.succeed(""),
        ),
    )
    yield from input_key("a")
    yield from input_key("b")
    yield from input_key("c")
    assert (yield from prompt.run(custom)) == 3


@testing.effect
def test_input_variant_exposes_the_input_field_with_user_input(env: Services[Env]):
    """Input variant exposes the input field with UserInput"""
    events = yield from Queue[str, Never].unbounded()

    def process(input: ProcessInput[str], state: str) -> fx.Effect[Action[str, str]]:
        match input:
            case Input(user_input):
                key = user_input.key.name
                return fx.succeed(Submit(state) if key == "enter" else NextFrame(state + key))
            case Event():
                return fx.succeed(NextFrame(state))

    custom = prompt.custom(
        "",
        events,
        Handlers(
            lambda state, _: fx.succeed(f"Captured: {state}"),
            process,
            lambda _s, _a: fx.succeed(""),
        ),
    )
    yield from input_key("x")
    yield from input_key("y")
    yield from input_key("enter")
    assert (yield from prompt.run(custom)) == "xy"
