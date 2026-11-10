"""Effect's ``test/cli/services/MockTerminal.ts``: a terminal fed key
presses by the test, recording everything displayed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Never, cast

import pyfect as fx
from pyfect import layer, scope
from pyfect.errors import Done
from pyfect.queue import Queue
from pyfect.terminal import Key, Size, Terminal, TerminalService, UserInput


@dataclass(frozen=True, slots=True, kw_only=True)
class MockTerminalService(TerminalService):
    output: list[str] = field(default_factory=list[str])
    queue: Queue[UserInput, Done] = field(default_factory=Queue[UserInput, Done])

    def input_text(self, text: str) -> fx.Effect[None]:
        return self.queue.offer_all([_user_input(ch) for ch in text]).as_(None)

    def input_key(
        self, key: str, *, ctrl: bool = False, meta: bool = False, shift: bool = False
    ) -> fx.Effect[None]:
        event = _user_input(key, ctrl=ctrl, meta=meta, shift=shift)
        if ctrl and key in ("c", "d"):
            return self.queue.end().as_(None)
        return self.queue.offer(event).as_(None)


def _user_input(
    key: str, *, ctrl: bool = False, meta: bool = False, shift: bool = False
) -> UserInput:
    return UserInput(key, Key(key, ctrl=ctrl, meta=meta, shift=shift))


def _make() -> fx.Effect[MockTerminalService, Never, scope.Scope]:
    def body():
        queue = yield from scope.acquire_release(
            Queue[UserInput, Done].unbounded(), lambda q, _: q.shutdown()
        )
        output: list[str] = []

        def display(text: str) -> fx.Effect[None]:
            return fx.sync(lambda: output.append(text))

        @fx.fn
        def size():
            sizes = yield from Queue[Size, Done].unbounded()
            yield from sizes.offer(Size(80, 24))
            return sizes

        return MockTerminalService(
            columns=fx.succeed(80),
            rows=fx.succeed(24),
            size=size(),
            display=display,
            read_input=fx.succeed(queue),
            read_line=fx.succeed(""),
            output=output,
            queue=queue,
        )

    return fx.gen(body)


mock_terminal_layer = layer.effect(Terminal, _make())


def _mock() -> fx.Effect[MockTerminalService, Never, Terminal]:
    return Terminal().map(lambda service: cast("MockTerminalService", service))


def display_lines() -> fx.Effect[list[str], Never, Terminal]:
    return _mock().map(lambda mock: list(mock.output))


def input_text(text: str) -> fx.Effect[None, Never, Terminal]:
    return _mock().flat_map(lambda mock: mock.input_text(text))


def input_key(
    key: str, *, ctrl: bool = False, meta: bool = False, shift: bool = False
) -> fx.Effect[None, Never, Terminal]:
    return _mock().flat_map(lambda mock: mock.input_key(key, ctrl=ctrl, meta=meta, shift=shift))
