"""Interactive prompts on the ``Terminal`` service (Effect's ``Prompt``).

A prompt is an effect: ``yield from prompt`` (or ``run(prompt)``) asks it.
Prompts combine with ``map``, ``flat_map`` and ``all``; ``custom`` builds
new ones from render / process / clear handlers. Styling comes from the
``PromptTheme`` reference, overridable per prompt with ``theme=``.
"""

from pyfect.cli.prompt._auto_complete import auto_complete
from pyfect.cli.prompt._choices import Choice
from pyfect.cli.prompt._confirm import confirm, toggle
from pyfect.cli.prompt._core import (
    Action,
    Beep,
    Event,
    Handlers,
    Input,
    NextFrame,
    ProcessInput,
    Prompt,
    PromptEnvironment,
    PromptTheme,
    Submit,
    Theme,
    ThemeOptions,
    all,
    custom,
    make_theme,
    run,
)
from pyfect.cli.prompt._core import prompt_succeed as succeed
from pyfect.cli.prompt._date import date
from pyfect.cli.prompt._date_parts import Locales
from pyfect.cli.prompt._file import FileType, file
from pyfect.cli.prompt._multi_select import multi_select
from pyfect.cli.prompt._number import integer, number
from pyfect.cli.prompt._select import select
from pyfect.cli.prompt._text import hidden, list_, password, string

__all__ = [
    "Action",
    "Beep",
    "Choice",
    "Event",
    "FileType",
    "Handlers",
    "Input",
    "Locales",
    "NextFrame",
    "ProcessInput",
    "Prompt",
    "PromptEnvironment",
    "PromptTheme",
    "Submit",
    "Theme",
    "ThemeOptions",
    "all",
    "auto_complete",
    "confirm",
    "custom",
    "date",
    "file",
    "hidden",
    "integer",
    "list_",
    "make_theme",
    "multi_select",
    "number",
    "password",
    "run",
    "select",
    "string",
    "succeed",
    "toggle",
]
