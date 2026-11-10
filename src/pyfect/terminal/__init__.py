"""The terminal as a service (Effect's ``Terminal``): its size, a line or
key presses from the user, and text shown to them::

    term = yield from Terminal()
    yield from term.display("Name? ")
    name = yield from term.read_line   # QuitError at the end of input

``layer`` is standard input and output (``live(should_quit=...)`` for
another quit key); ``TerminalService(...)`` builds one for tests.
"""

from pyfect._public import publish
from pyfect.layer import Layer
from pyfect.layer import sync as _layer_sync
from pyfect.terminal._keys import decode
from pyfect.terminal._live import live
from pyfect.terminal._service import (
    Key,
    QuitError,
    Size,
    Terminal,
    TerminalService,
    UserInput,
    default_should_quit,
)

layer: Layer[Terminal] = _layer_sync(Terminal, live)
"""Standard input and output."""

__all__ = [
    "Key",
    "QuitError",
    "Size",
    "Terminal",
    "TerminalService",
    "UserInput",
    "decode",
    "default_should_quit",
    "layer",
    "live",
]

publish(globals())
