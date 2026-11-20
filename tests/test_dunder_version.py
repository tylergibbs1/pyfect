"""``pyfect.__version__`` is the installed distribution's version, where newcomers look first."""

from importlib.metadata import version

import pyfect


def test_dunder_version_is_the_installed_distributions_version() -> None:
    assert pyfect.__version__ == version("pyfect-dev")
