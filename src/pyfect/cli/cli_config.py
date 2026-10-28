"""Settings of the CLI runner (Effect's ``CliConfig``): which built-in
global flags every command gets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pyfect.cli import global_flag
from pyfect.cli._settings import GlobalFlag
from pyfect.context import Reference
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed


@dataclass(frozen=True, slots=True)
class Settings:
    built_ins: tuple[GlobalFlag, ...] = global_flag.built_ins


defaults = Settings()


class CliConfig(Reference[Settings]):
    """The runner's settings; defaults to ``defaults``."""

    @classmethod
    def default(cls) -> Settings:
        return defaults


def make(*, built_ins: Sequence[GlobalFlag] | None = None) -> Settings:
    return Settings(defaults.built_ins if built_ins is None else tuple(built_ins))


def layer(*, built_ins: Sequence[GlobalFlag] | None = None) -> Layer[CliConfig]:
    return layer_succeed(CliConfig, make(built_ins=built_ins))


__all__ = ["CliConfig", "Settings", "defaults", "layer", "make"]
