"""``pyfect.__version__`` is the installed distribution's version, where newcomers look first."""

from importlib.metadata import version

import pyfect


def test_dunder_version_is_the_installed_distributions_version() -> None:
    assert pyfect.__version__ == version("pyfect-dev")


def test_importing_pyfect_does_not_read_its_metadata() -> None:
    # A source tree on PYTHONPATH has no installed metadata: the import must not need it.
    import subprocess
    import sys

    code = (
        "import importlib.metadata as m\n"
        "real = m.version\n"
        "def version(name):\n"
        "    if name == 'pyfect-dev': raise m.PackageNotFoundError(name)\n"
        "    return real(name)\n"
        "m.version = version\n"
        "import pyfect\n"
        "print('imported')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.stdout.strip() == "imported", done.stderr
