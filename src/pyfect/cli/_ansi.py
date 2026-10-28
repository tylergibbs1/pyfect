"""ANSI escape sequences for the CLI's rendering (Effect's internal
``cli/internal/ansi``): styles, cursor movement and line erasing, as plain
strings so renderers compose them in order."""

from __future__ import annotations

import os
import sys

ESC = "\x1b["
BEL = "\x07"

reset = f"{ESC}0m"
bold = f"{ESC}1m"
italicized = f"{ESC}3m"
underlined = f"{ESC}4m"
strikethrough = f"{ESC}9m"
cursor_show = f"{ESC}?25h"
cursor_hide = f"{ESC}?25l"
cursor_left = f"{ESC}G"
cursor_save_position = f"{ESC}s"
cursor_restore_position = f"{ESC}u"
erase_line = f"{ESC}2K"
beep = BEL

red = f"{ESC}31m"
green = f"{ESC}32m"
magenta = f"{ESC}35m"
white = f"{ESC}37m"
black_bright = f"{ESC}90m"
cyan_bright = f"{ESC}96m"


def annotate(colors: bool, text: str, *styles: str) -> str:
    """``text`` in ``styles`` followed by a reset; unchanged without
    ``colors``, so color is gated in one place while cursor controls are not."""
    if not colors:
        return text
    return f"{''.join(styles)}{text}{reset}"


def detect_colors() -> bool:
    """Whether output should be styled: stdout is a terminal and ``NO_COLOR``
    is unset or empty."""
    stdout = sys.stdout
    try:
        tty = stdout is not None and stdout.isatty()
    except ValueError:
        tty = False
    return tty and not os.environ.get("NO_COLOR")


def cursor_to(column: int, row: int | None = None) -> str:
    if row is None:
        return f"{ESC}{max(column + 1, 0)}G"
    return f"{ESC}{row + 1};{max(column + 1, 0)}H"


def cursor_down(lines: int = 1) -> str:
    return f"{ESC}{lines}B"


def cursor_move(column: int, row: int = 0) -> str:
    command = ""
    if row < 0:
        command += f"{ESC}{-row}A"
    if row > 0:
        command += f"{ESC}{row}B"
    if column > 0:
        command += f"{ESC}{column}C"
    if column < 0:
        command += f"{ESC}{-column}D"
    return command


def erase_lines(rows: int) -> str:
    command = ""
    for i in range(rows):
        command += f"{ESC}2K" + (f"{ESC}1A" if i < rows - 1 else "")
    if rows > 0:
        command += f"{ESC}G"
    return command
