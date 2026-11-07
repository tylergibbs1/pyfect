"""pyfect's version (Effect's ``Version.getCurrentVersion()``)."""

from importlib.metadata import version
from typing import Final

from pyfect._extras import DISTRIBUTION

VERSION: Final = version(DISTRIBUTION)
"""The installed distribution's version."""
