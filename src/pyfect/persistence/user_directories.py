"""Where a program keeps its files per user (Effect's
``effect/persistence/UserDirectories``). Provide ``user_directories.layer``;
``platform.layer`` doesn't include it (nor does Effect's ``NodeServices``)::

    @fx.fn
    def config_dir():
        dirs = yield from UserDirectories()
        return (yield from dirs.config("myapp"))   # ~/.config/myapp on Linux

    path = fx.run_blocking(config_dir().pipe(fx.provide(user_directories.layer)))

An absolute ``XDG_CONFIG_HOME`` / ``XDG_DATA_HOME`` / ``XDG_CACHE_HOME`` /
``XDG_STATE_HOME`` wins on every platform. Otherwise macOS uses
``~/Library/Application Support`` (``~/Library/Caches`` for the cache),
Windows ``APPDATA`` / ``LOCALAPPDATA`` (or ``AppData`` under
``USERPROFILE``, the cache in a ``Cache`` folder), and other systems the
XDG defaults. The variables are read from the ``ConfigProvider`` on every
call.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from pyfect import config
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Tag
from pyfect.effect import fail, succeed
from pyfect.layer import Layer
from pyfect.layer import sync as layer_sync
from pyfect.platform_error import PlatformError, system_error

type Kind = Literal["config", "data", "cache", "state"]

_XDG: Final[dict[Kind, str]] = {
    "config": "XDG_CONFIG_HOME",
    "data": "XDG_DATA_HOME",
    "cache": "XDG_CACHE_HOME",
    "state": "XDG_STATE_HOME",
}

_WINDOWS_ABSOLUTE: Final = re.compile(r"^([a-zA-Z]:)?[\\/]")


@dataclass(frozen=True, slots=True, kw_only=True)
class UserDirectoriesService:
    """The user's home and each kind of directory for an application
    name. A missing home fails with ``NotFound``; a ``ConfigProvider``
    that cannot be read with ``Unknown``."""

    home: Effect[str, PlatformError]
    config: Callable[[str], Effect[str, PlatformError]]
    data: Callable[[str], Effect[str, PlatformError]]
    cache: Callable[[str], Effect[str, PlatformError]]
    state: Callable[[str], Effect[str, PlatformError]]

    def __post_init__(self) -> None:
        require_effect(self.home, "home")


class UserDirectories(Tag[UserDirectoriesService], key="~effect/persistence/UserDirectories"):
    """The per-user directories a program uses."""


@dataclass(frozen=True, slots=True)
class _Environment:
    home: str | None
    xdg: str | None
    app_data: str | None


def _is_absolute(platform: str, path: str) -> bool:
    if platform == "win32":
        return _WINDOWS_ABSOLUTE.match(path) is not None
    return path.startswith("/")


def _join(platform: str, base: str, *segments: str) -> str:
    if platform == "win32":
        return "\\".join([re.sub(r"[\\/]+$", "", base), *segments])
    return "/".join([re.sub(r"/+$", "", base), *segments])


def _windows_base(kind: Kind, env: _Environment) -> str | None:
    if env.app_data is not None and _is_absolute("win32", env.app_data):
        return env.app_data
    if env.home is None:
        return None
    roaming = kind in ("config", "data")
    return _join("win32", env.home, "AppData", "Roaming" if roaming else "Local")


def _posix_base(platform: str, kind: Kind, home: str) -> str:
    if platform == "darwin":
        return _join(
            platform, home, "Library", "Caches" if kind == "cache" else "Application Support"
        )
    match kind:
        case "config":
            return _join(platform, home, ".config")
        case "data":
            return _join(platform, home, ".local", "share")
        case "cache":
            return _join(platform, home, ".cache")
        case "state":
            return _join(platform, home, ".local", "state")


def _resolve(platform: str, kind: Kind, app_name: str, env: _Environment) -> str | None:
    if env.xdg is not None and _is_absolute(platform, env.xdg):
        return _join(platform, env.xdg, app_name)
    if platform == "win32":
        base = _windows_base(kind, env)
        if base is None:
            return None
        if kind == "cache":
            return _join(platform, base, app_name, "Cache")
        return _join(platform, base, app_name)
    if env.home is None:
        return None
    return _join(platform, _posix_base(platform, kind, env.home), app_name)


def make(*, platform: str | None = None) -> UserDirectoriesService:
    """The directories by ``platform``'s rules (``"linux"``, ``"darwin"``,
    ``"win32"``, ...; default: ``sys.platform``)."""
    name = sys.platform if platform is None else platform
    home_variable = "USERPROFILE" if name == "win32" else "HOME"

    def optional_string(variable: str) -> config.Config[str | None]:
        return config.string(variable).with_default(None)

    def read[A](method: str, source: config.Config[A]) -> Effect[A, PlatformError]:
        return source.map_error(
            lambda cause: system_error(
                "Unknown",
                module="UserDirectories",
                method=method,
                description="Failed to read the environment",
                cause=cause,
            )
        )

    def not_found(method: str) -> PlatformError:
        return system_error(
            "NotFound",
            module="UserDirectories",
            method=method,
            description=f"{home_variable} is not set",
        )

    def directory(kind: Kind) -> Callable[[str], Effect[str, PlatformError]]:
        app_data = "APPDATA" if kind in ("config", "data") else "LOCALAPPDATA"
        environment = config.all(
            optional_string(home_variable), optional_string(_XDG[kind]), optional_string(app_data)
        ).map(lambda values: _Environment(*values))

        def resolve(app_name: str) -> Effect[str, PlatformError]:
            def found(env: _Environment) -> Effect[str, PlatformError]:
                resolved = _resolve(name, kind, app_name, env)
                return fail(not_found(kind)) if resolved is None else succeed(resolved)

            return read(kind, environment).flat_map(found)

        return resolve

    def home(found: str | None) -> Effect[str, PlatformError]:
        return fail(not_found("home")) if found is None else succeed(found)

    return UserDirectoriesService(
        home=read("home", optional_string(home_variable)).flat_map(home),
        config=directory("config"),
        data=directory("data"),
        cache=directory("cache"),
        state=directory("state"),
    )


layer: Layer[UserDirectories] = layer_sync(UserDirectories, make)
"""The host's directories."""


def layer_platform(platform: str) -> Layer[UserDirectories]:
    """``platform``'s directories."""
    return layer_sync(UserDirectories, lambda: make(platform=platform))


__all__ = [
    "Kind",
    "UserDirectories",
    "UserDirectoriesService",
    "layer",
    "layer_platform",
    "make",
]
