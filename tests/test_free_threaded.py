"""The cross-thread stress (``tests/free_threaded/stress.py``) under a
free-threaded CPython. With the GIL, thread switches land only between
bytecodes, which hides races such as a resume from another thread racing
the end of callback registration (QA concurrency 2: the run hung on
3.14t). Skipped when no free-threaded build is installed
(``uv python install 3.14t``), unless ``PYFECT_REQUIRE_FREE_THREADED`` is
set, as the free-threaded CI job sets it."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pyfect._extras import LIBRARIES

ROOT = Path(__file__).parent.parent
STRESS = Path(__file__).parent / "free_threaded" / "stress.py"


def _free_threaded_python() -> str | None:
    uv = shutil.which("uv")
    if uv is None:
        return None
    found = subprocess.run(
        [uv, "python", "find", "--no-project", "3.14t"],
        capture_output=True,
        text=True,
        check=False,
    )
    path = found.stdout.strip()
    return path if found.returncode == 0 and path else None


def test_the_cross_thread_stress_passes_without_the_gil(tmp_path: Path):
    python = _free_threaded_python()
    if python is None:
        if os.environ.get("PYFECT_REQUIRE_FREE_THREADED"):
            pytest.fail("PYFECT_REQUIRE_FREE_THREADED is set but uv finds no CPython 3.14t")
        pytest.skip("no free-threaded CPython 3.14t (uv python install 3.14t)")
    import typing_extensions

    # pyfect's sources, and its one dependency (a single module) copied
    # from this environment.
    shutil.copy(typing_extensions.__file__, tmp_path)
    path = os.pathsep.join([str(ROOT / "src"), str(tmp_path)])
    env = {**os.environ, "PYTHONPATH": path, "PYTHON_GIL": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(
        [python, "-B", str(STRESS)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )
    assert "GIL enabled: False" in done.stdout, done.stdout + done.stderr
    assert done.returncode == 0, done.stdout + done.stderr[-4000:]


def test_the_stress_also_passes_here():
    """The same invariants on this interpreter (normally with the GIL)."""
    done = subprocess.run(
        [sys.executable, "-B", str(STRESS)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr[-4000:]


_IMPORT_EVERY_LIBRARY = """
import importlib, importlib.metadata, sys

names = sorted(
    {name for name in importlib.metadata.packages_distributions() if not name.startswith("_")}
)
for name in names:
    try:
        importlib.import_module(name)
    except Exception:
        continue
    if sys._is_gil_enabled():
        print(f"importing {name} enabled the GIL")
        break
else:
    print("GIL enabled: False")
"""


def test_every_extra_keeps_the_gil_off(tmp_path: Path):
    # A C extension that does not declare free-threading support turns the
    # GIL back on for the whole process as soon as it is imported, even when
    # another library imports it (httpx imports brotli if it is installed).
    python = _free_threaded_python()
    if python is None:
        if os.environ.get("PYFECT_REQUIRE_FREE_THREADED"):
            pytest.fail("PYFECT_REQUIRE_FREE_THREADED is set but uv finds no CPython 3.14t")
        pytest.skip("no free-threaded CPython 3.14t (uv python install 3.14t)")
    extras = ",".join(sorted(LIBRARIES))
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "-q", "--python", python, str(venv)], check=True)
    target = venv / "bin" / "python"
    install = ["uv", "pip", "install", "-q", "--python", str(target), f"{ROOT}[{extras}]"]
    if subprocess.run([*install, "--offline"], capture_output=True, check=False).returncode:
        subprocess.run(install, capture_output=True, check=True)
    env = {name: value for name, value in os.environ.items() if name != "PYTHON_GIL"}
    done = subprocess.run(
        [str(target), "-I", "-c", _IMPORT_EVERY_LIBRARY],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )
    assert done.stdout.strip().splitlines()[-1:] == ["GIL enabled: False"], (
        done.stdout + done.stderr[-4000:]
    )
