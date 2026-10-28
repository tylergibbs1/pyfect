"""The host's platform services in one layer (Effect's ``NodeServices``)::

    fx.run_main(program.pipe(fx.provide(platform.layer)))

provides the live ``FileSystem``, ``Path``, ``Stdio`` and ``Terminal``.
"""

from __future__ import annotations

from pyfect import file_system, path, stdio, terminal
from pyfect.file_system import FileSystem
from pyfect.layer import Layer, merge
from pyfect.path import Path
from pyfect.stdio import Stdio
from pyfect.terminal import Terminal

type PlatformServices = FileSystem | Path | Stdio | Terminal

layer: Layer[PlatformServices] = merge(file_system.layer, path.layer, stdio.layer, terminal.layer)

__all__ = ["PlatformServices", "layer"]
