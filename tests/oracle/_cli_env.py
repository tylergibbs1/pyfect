"""The services Effect's ``test/cli`` suites run commands with, and
``services/TestActions.ts``: a log of what handlers did."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Never

import pyfect as fx
from pyfect import layer, path
from pyfect.byte_size import ByteSize
from pyfect.cli import cli_output
from pyfect.cli.terminal_capabilities import Capabilities, TerminalCapabilities
from pyfect.context import Tag
from pyfect.file_system import FileInfo, FileSystem, FileType, NoopFileSystem, layer_noop
from pyfect.process import ChildProcessSpawner
from pyfect.process._spawner import ChildProcessSpawnerService
from pyfect.stdio import layer_test as stdio_layer_test

from ._mock_terminal import mock_terminal_layer


@dataclass(frozen=True, slots=True)
class TestAction:
    __test__ = False

    command: str
    details: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class TestActionsService:
    __test__ = False

    actions: list[TestAction] = field(default_factory=list[TestAction])


class TestActions(Tag[TestActionsService]):
    __test__ = False


def log_action(
    command: str, details: dict[str, Any] | None = None
) -> fx.Effect[None, Never, TestActions]:
    action = TestAction(command, details or {})
    return TestActions().map(lambda service: service.actions.append(action))


def get_actions() -> fx.Effect[list[TestAction], Never, TestActions]:
    return TestActions().map(lambda service: list(service.actions))


actions_layer = layer.sync(TestActions, TestActionsService)


def _not_implemented(_: object) -> fx.Effect[Never]:
    return fx.die(NotImplementedError("Not implemented"))


spawner_layer = layer.succeed(ChildProcessSpawner, ChildProcessSpawnerService(_not_implemented))

no_color_capabilities = Capabilities(can_color=False, can_animate=False, can_prompt=True)

base_layer = layer.merge(
    layer_noop(),
    path.layer,
    mock_terminal_layer,
    spawner_layer,
    stdio_layer_test(),
)
"""Effect's ``TestLayerWithoutFormatter`` (the test console comes from the
runner)."""

test_layer = layer.merge(
    base_layer,
    actions_layer,
    cli_output.layer(cli_output.default_formatter(colors=False)),
)
"""Effect's ``TestLayer``: the above, test actions and an uncolored
formatter."""

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def capabilities_layer(capabilities: Capabilities = no_color_capabilities):
    return layer.succeed(TerminalCapabilities, capabilities)


def file_info(kind: FileType) -> FileInfo:
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


def with_file_system[A, E, R](
    eff: fx.Effect[A, E, R], file_system: NoopFileSystem
) -> fx.Effect[A, E, R]:
    """``eff`` with ``file_system`` in place of the environment's."""
    return eff.pipe(fx.provide_service(FileSystem, file_system))
