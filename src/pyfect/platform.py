"""The host's platform services in one layer (Effect's ``NodeServices``)::

    fx.run_main(program.pipe(fx.provide(platform.layer)))

provides the live ``FileSystem``, ``Path``, ``Stdio``, ``Terminal`` and
``ChildProcessSpawner``. Cryptography is provided explicitly, with
``crypto.native.layer`` or a family's own layer.
"""

from __future__ import annotations

from pyfect import file_system, path, process, stdio, terminal
from pyfect.file_system import FileSystem
from pyfect.layer import Layer, merge, provide_merge
from pyfect.path import Path
from pyfect.process import ChildProcessSpawner
from pyfect.stdio import Stdio
from pyfect.terminal import Terminal

type PlatformServices = ChildProcessSpawner | FileSystem | Path | Stdio | Terminal

layer: Layer[PlatformServices] = process.layer.pipe(
    provide_merge(merge(file_system.layer, path.layer, stdio.layer, terminal.layer))
)
"""The live ``FileSystem``, ``Path``, ``Stdio``, ``Terminal`` and ``ChildProcessSpawner``."""

__all__ = ["PlatformServices", "layer"]
