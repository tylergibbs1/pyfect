"""What the terminal running the CLI can do (Effect's
``TerminalCapabilities``): color output, animation and interactive prompts.

The ``TerminalCapabilities`` reference defaults to the process's own
streams and environment; ``layer`` reads them through ``Stdio`` and the
current ``ConfigProvider`` instead, so tests can pick them::

    caps = yield from TerminalCapabilities()
    if caps.can_prompt: ...

``TERM=dumb`` turns everything off; ``NO_COLOR`` (non-empty) turns color off;
``FORCE_COLOR`` (non-empty, not ``0`` or ``false``) turns it on without a
terminal.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import IO, Any, Never

from pyfect import config as config_
from pyfect.context import Reference
from pyfect.effect import Effect, gen
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.option import Option, Some
from pyfect.stdio import Stdio


@dataclass(frozen=True, slots=True)
class Capabilities:
    can_color: bool
    can_animate: bool
    can_prompt: bool


def _present(value: str | None) -> bool:
    return value is not None and len(value) > 0


def _forcing(value: str | None) -> bool:
    return _present(value) and value != "0" and (value or "").lower() != "false"


def detect(
    *,
    no_color: str | None,
    force_color: str | None,
    term: str | None,
    stdin_is_terminal: bool,
    stdout_is_terminal: bool,
) -> Capabilities:
    if term == "dumb":
        return Capabilities(can_color=False, can_animate=False, can_prompt=False)
    return Capabilities(
        can_color=not _present(no_color) and (_forcing(force_color) or stdout_is_terminal),
        can_animate=stdout_is_terminal,
        can_prompt=stdin_is_terminal and stdout_is_terminal,
    )


def _isatty(stream: IO[Any] | None) -> bool:
    try:
        return stream is not None and stream.isatty()
    except ValueError:
        return False


def from_process() -> Capabilities:
    """The capabilities of this process's standard streams and environment."""
    return detect(
        no_color=os.environ.get("NO_COLOR"),
        force_color=os.environ.get("FORCE_COLOR"),
        term=os.environ.get("TERM"),
        stdin_is_terminal=_isatty(sys.stdin),
        stdout_is_terminal=_isatty(sys.stdout),
    )


class TerminalCapabilities(Reference[Capabilities]):
    """The capabilities in use; defaults to ``from_process()``."""

    @classmethod
    def default(cls) -> Capabilities:
        return from_process()


def _value(option: Option[str]) -> str | None:
    return option.value if isinstance(option, Some) else None


def _make() -> Effect[Capabilities, Never, Stdio]:
    def body():
        stdio = yield from Stdio()
        env = yield from config_.all(
            config_.option(config_.string("NO_COLOR")),
            config_.option(config_.string("FORCE_COLOR")),
            config_.option(config_.string("TERM")),
        ).or_die()
        no_color, force_color, term = env
        return detect(
            no_color=_value(no_color),
            force_color=_value(force_color),
            term=_value(term),
            stdin_is_terminal=(yield from stdio.stdin_is_terminal),
            stdout_is_terminal=(yield from stdio.stdout_is_terminal),
        )

    return gen(body)


layer: Layer[Never, Never, Stdio] = layer_effect(TerminalCapabilities, _make())
"""Capabilities read from ``Stdio`` and the ``NO_COLOR``, ``FORCE_COLOR`` and
``TERM`` config keys."""

__all__ = ["Capabilities", "TerminalCapabilities", "detect", "from_process", "layer"]
