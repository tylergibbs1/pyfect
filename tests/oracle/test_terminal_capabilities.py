"""Effect's ``test/cli/TerminalCapabilities.test.ts``."""

from __future__ import annotations

import pyfect as fx
from pyfect import config_provider, testing
from pyfect.cli import terminal_capabilities
from pyfect.cli.terminal_capabilities import Capabilities, TerminalCapabilities
from pyfect.stdio import layer_test


def detect(
    env: dict[str, str], *, stdin: bool = False, stdout: bool = False
) -> fx.Effect[Capabilities]:
    return (
        TerminalCapabilities()
        .pipe(fx.provide(terminal_capabilities.layer))
        .pipe(
            fx.provide(
                layer_test(
                    stdin_is_terminal=fx.succeed(stdin), stdout_is_terminal=fx.succeed(stdout)
                )
            )
        )
        .pipe(fx.provide(config_provider.layer(config_provider.from_env(env))))
    )


@testing.effect
def test_has_a_default_when_nothing_is_provided():
    """has a default when nothing is provided"""
    capabilities = yield from TerminalCapabilities()
    assert isinstance(capabilities.can_color, bool)
    assert isinstance(capabilities.can_animate, bool)
    assert isinstance(capabilities.can_prompt, bool)


@testing.effect
def test_follows_the_terminals_when_no_overrides_are_set():
    """follows the terminals when no overrides are set"""
    assert (yield from detect({}, stdin=True, stdout=True)) == Capabilities(True, True, True)
    assert (yield from detect({}, stdin=True)) == Capabilities(False, False, False)


@testing.effect
def test_forces_color_with_force_color_unless_it_is_empty_0_or_false():
    """forces color with FORCE_COLOR unless it is empty, 0 or false"""
    assert (yield from detect({"FORCE_COLOR": "1"})).can_color
    assert not (yield from detect({"FORCE_COLOR": ""})).can_color
    assert not (yield from detect({"FORCE_COLOR": "0"})).can_color
    assert not (yield from detect({"FORCE_COLOR": "false"})).can_color
    assert (yield from detect({"FORCE_COLOR": "0"}, stdout=True)).can_color
    assert (yield from detect({"FORCE_COLOR": "false"}, stdout=True)).can_color


@testing.effect
def test_lets_no_color_win_over_force_color_unless_it_is_empty():
    """lets NO_COLOR win over FORCE_COLOR unless it is empty"""
    assert not (yield from detect({"NO_COLOR": "1", "FORCE_COLOR": "1"}, stdout=True)).can_color
    assert (yield from detect({"NO_COLOR": "", "FORCE_COLOR": "1"})).can_color


@testing.effect
def test_clears_every_flag_when_term_is_dumb():
    """clears every flag when TERM is dumb"""
    result = yield from detect({"TERM": "dumb", "FORCE_COLOR": "1"}, stdin=True, stdout=True)
    assert result == Capabilities(False, False, False)
