"""The services a CLI's parsing, prompts and handlers may use (Effect's
``Command.Environment``)."""

from pyfect.file_system import FileSystem
from pyfect.path import Path
from pyfect.process import ChildProcessSpawner
from pyfect.stdio import Stdio
from pyfect.terminal import Terminal

type Environment = FileSystem | Path | Terminal | ChildProcessSpawner | Stdio
