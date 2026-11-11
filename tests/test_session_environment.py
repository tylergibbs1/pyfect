"""Child processes started during the test run inherit exactly ``os.environ``.

pytest imports ``readline`` before ``conftest.py`` loads (``_readline_workaround``). GNU
readline (Linux) then exports ``COLUMNS=80`` and ``LINES=24`` into the C environment without
``os.environ`` seeing them, so every child inherited them: ``ps aux`` cut its lines at 80
columns and the Effect process-supervision ports counted 0 processes on Linux CI.
"""

import os
import subprocess


def test_a_child_inherits_exactly_os_environ():
    output = subprocess.run(["env", "-0"], capture_output=True, check=True).stdout
    inherited = dict(entry.split("=", 1) for entry in output.decode().split("\0") if entry)
    assert inherited == dict(os.environ)
