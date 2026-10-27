"""Reading one node: provider failures as ``ConfigError``, and the scalar
configs built on a ``Scalar`` decoder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

from pyfect._core import Effect
from pyfect.cause import Cause, Die, Fail, Interrupt, Reason
from pyfect.config._config import Config, Resolution
from pyfect.config._error import ConfigError
from pyfect.config._issue import Issue, Pointer, SchemaError
from pyfect.config_provider import ConfigProvider, Node, Path, SourceError
from pyfect.effect import fail, fail_cause, succeed
from pyfect.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class Scalar[A]:
    """How a config reads a value from one string: ``missing`` is the issue
    when the node holds no string, ``decode`` parses one."""

    missing: Issue
    decode: Callable[[str], Result[A, Issue]]


def scalar_config[A](scalar: Scalar[A], name: str | None) -> Config[A]:
    local: Path = () if name is None else (name,)

    def run(provider: ConfigProvider, prefix: Path) -> Effect[Resolution[A], ConfigError]:
        path = (*prefix, *local)

        def decode(node: Node | None) -> Effect[Resolution[A], ConfigError]:
            value = None if node is None else node.value
            if value is None:
                return succeed(absent(path, scalar.missing))
            match scalar.decode(value):
                case Ok() as ok:
                    return succeed(ok)
                case Err(issue):
                    return fail(invalid(path, issue))

        return load(provider, path).flat_map(decode)

    return Config(run)


def load(provider: ConfigProvider, path: Path) -> Effect[Node | None, ConfigError]:
    """``provider.load(path)``, failing with ``ConfigError`` where the
    provider fails, or dies, with a ``SourceError``. Other defects and
    interruptions are kept."""
    return provider.load(path).catch_cause(
        lambda cause: fail_cause(Cause(tuple(map(_source_reason, cause.reasons))))
    )


def _source_reason(reason: Reason[SourceError]) -> Reason[ConfigError]:
    match reason:
        case Fail(error) | Die(SourceError() as error):
            return Fail(ConfigError(error), annotations=reason.annotations)
        case Die() | Interrupt():
            return reason


def at(path: Path, issue: Issue) -> Issue:
    return Pointer(path, issue) if path else issue


def invalid(path: Path, issue: Issue) -> ConfigError:
    return ConfigError(SchemaError(at(path, issue)))


def absent(path: Path, issue: Issue) -> Resolution[Never]:
    return Err(invalid(path, issue))
