"""The host's platform services in one layer (Effect's ``NodeServices``)::

    fx.run_main(program.pipe(fx.provide(platform.layer)))

provides the live ``Crypto``, ``FileSystem``, ``Path``, ``Stdio``,
``Terminal`` and ``ChildProcessSpawner``.
"""

from __future__ import annotations

from pyfect import crypto, file_system, path, process, stdio, terminal
from pyfect.crypto import Crypto
from pyfect.file_system import FileSystem
from pyfect.layer import Layer, merge, provide_merge
from pyfect.path import Path
from pyfect.process import ChildProcessSpawner
from pyfect.stdio import Stdio
from pyfect.terminal import Terminal

type PlatformServices = ChildProcessSpawner | Crypto | FileSystem | Path | Stdio | Terminal

layer: Layer[PlatformServices] = process.layer.pipe(
    provide_merge(merge(crypto.layer, file_system.layer, path.layer, stdio.layer, terminal.layer))
)

__all__ = ["PlatformServices", "layer"]
