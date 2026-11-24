"""Which programs the host refuses to spawn without ``shell`` (Node's
CVE-2024-27980 check), shared by every place pyfect starts a process."""

from __future__ import annotations

import os
import sys


def current_platform() -> str:
    """Node's ``process.platform`` for this host (``"win32"`` on Windows)."""
    return "win32" if os.name == "nt" else sys.platform


_BATCH_EXTENSIONS = (".bat", ".cmd")


def refuses_batch_file(program: str, *, shell: bool | str, platform: str) -> bool:
    """Whether spawning ``program`` is refused: on Windows a batch file runs
    through ``cmd.exe``, which parses its arguments again, so (as Node does
    since CVE-2024-27980) one runs only with ``shell``. The file name is
    compared without case and without the trailing dots and spaces (or
    ``::$DATA`` stream) Windows drops; a name without an extension gets
    ``.exe``, so ``PATH`` never resolves one to a batch file."""
    if platform != "win32" or shell is not False:
        return False
    name = program.lower()
    name = name.removesuffix("::$data").rstrip(" .")
    return name.endswith(_BATCH_EXTENSIONS)
