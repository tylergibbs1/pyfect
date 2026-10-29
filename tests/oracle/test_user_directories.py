"""Ports of Effect's ``test/persistence/UserDirectories.test.ts``.

Each test's docstring is the Effect test title. ``withEnv`` provides a
``CurrentConfigProvider`` reading the given variables; the
``Layer.succeed`` override replaces one member of ``make()``'s service
with ``dataclasses.replace``.
"""

import dataclasses
from typing import Any

import pyfect as fx
from pyfect import config_provider as cp
from pyfect import testing
from pyfect.persistence import user_directories as ud
from pyfect.platform_error import NotFound, PlatformError, Unknown


def _with_env[A, E](effect: fx.Effect[A, E, Any], env: dict[str, str]) -> fx.Effect[A, E, Any]:
    return effect.pipe(fx.provide_service(cp.CurrentConfigProvider, cp.from_env(env)))


def _resolve(platform: str, env: dict[str, str]) -> fx.Effect[dict[str, str], PlatformError]:
    dirs = ud.make(platform=platform)
    return _with_env(
        fx.all_dict(
            {
                "config": dirs.config("myapp"),
                "data": dirs.data("myapp"),
                "cache": dirs.cache("myapp"),
                "state": dirs.state("myapp"),
            }
        ),
        env,
    )


def _config(platform: str, env: dict[str, str]) -> fx.Effect[str, PlatformError]:
    return _with_env(ud.make(platform=platform).config("myapp"), env)


@testing.effect
def test_uses_absolute_xdg_directories_on_every_platform():
    """UserDirectories / uses absolute XDG directories on every platform"""
    assert (
        yield from _resolve(
            "linux",
            {
                "HOME": "/home/ada",
                "XDG_CONFIG_HOME": "/xdg/config",
                "XDG_DATA_HOME": "/xdg/data",
                "XDG_CACHE_HOME": "/xdg/cache",
                "XDG_STATE_HOME": "/xdg/state",
            },
        )
    ) == {
        "config": "/xdg/config/myapp",
        "data": "/xdg/data/myapp",
        "cache": "/xdg/cache/myapp",
        "state": "/xdg/state/myapp",
    }
    assert (
        yield from _config("linux", {"HOME": "/home/ada", "XDG_CONFIG_HOME": "/custom\\"})
    ) == "/custom\\/myapp"
    assert (
        yield from _config("darwin", {"HOME": "/Users/ada", "XDG_CONFIG_HOME": "/custom"})
    ) == "/custom/myapp"
    assert (
        yield from _config(
            "win32",
            {
                "USERPROFILE": "C:\\Users\\ada",
                "APPDATA": "C:\\AppData",
                "XDG_CONFIG_HOME": "D:\\custom",
            },
        )
    ) == "D:\\custom\\myapp"
    assert (
        yield from _with_env(
            ud.make(platform="win32").cache("myapp"),
            {
                "USERPROFILE": "C:\\Users\\ada",
                "LOCALAPPDATA": "C:\\Local",
                "XDG_CACHE_HOME": "D:\\cache",
            },
        )
    ) == "D:\\cache\\myapp"


@testing.effect
def test_falls_back_to_the_platform_defaults():
    """UserDirectories / falls back to the platform defaults"""
    assert (yield from _resolve("linux", {"HOME": "/home/ada", "XDG_CONFIG_HOME": "relative"})) == {
        "config": "/home/ada/.config/myapp",
        "data": "/home/ada/.local/share/myapp",
        "cache": "/home/ada/.cache/myapp",
        "state": "/home/ada/.local/state/myapp",
    }
    assert (yield from _resolve("darwin", {"HOME": "/Users/ada"})) == {
        "config": "/Users/ada/Library/Application Support/myapp",
        "data": "/Users/ada/Library/Application Support/myapp",
        "cache": "/Users/ada/Library/Caches/myapp",
        "state": "/Users/ada/Library/Application Support/myapp",
    }
    assert (
        yield from _resolve(
            "win32",
            {
                "USERPROFILE": "C:\\Users\\ada",
                "APPDATA": "D:\\Roaming",
                "LOCALAPPDATA": "D:\\Local",
            },
        )
    ) == {
        "config": "D:\\Roaming\\myapp",
        "data": "D:\\Roaming\\myapp",
        "cache": "D:\\Local\\myapp\\Cache",
        "state": "D:\\Local\\myapp",
    }
    assert (
        yield from _resolve(
            "win32",
            {"USERPROFILE": "C:\\Users\\ada", "APPDATA": "relative", "LOCALAPPDATA": "relative"},
        )
    ) == {
        "config": "C:\\Users\\ada\\AppData\\Roaming\\myapp",
        "data": "C:\\Users\\ada\\AppData\\Roaming\\myapp",
        "cache": "C:\\Users\\ada\\AppData\\Local\\myapp\\Cache",
        "state": "C:\\Users\\ada\\AppData\\Local\\myapp",
    }


@testing.effect
def test_resolves_the_home_directory():
    """UserDirectories / resolves the home directory"""
    env = {"HOME": "/home/ada", "USERPROFILE": "C:\\Users\\ada"}
    assert (yield from _with_env(ud.make(platform="win32").home, env)) == "C:\\Users\\ada"
    assert (yield from _with_env(ud.make(platform="linux").home, env)) == "/home/ada"


@testing.effect
def test_fails_with_not_found_when_no_home_directory_is_available():
    """UserDirectories / fails with NotFound when no home directory is available"""
    error = yield from _config("linux", {}).flip()
    assert isinstance(error, PlatformError)
    assert isinstance(error.reason, NotFound)
    assert error.reason.module == "UserDirectories"


@testing.effect
def test_fails_with_a_platform_error_when_the_config_provider_fails():
    """UserDirectories / fails with a PlatformError when the ConfigProvider fails"""
    failing = cp.make(lambda _path: fx.fail(cp.SourceError("unavailable")))
    error = yield from (
        ud.make(platform="linux")
        .config("myapp")
        .pipe(fx.provide_service(cp.CurrentConfigProvider, failing))
        .flip()
    )
    assert isinstance(error, PlatformError)
    assert isinstance(error.reason, Unknown)
    assert error.reason.module == "UserDirectories"


@testing.effect
def test_reads_the_environment_on_each_call():
    """UserDirectories / reads the environment on each call"""
    dirs = ud.make(platform="linux")
    assert (
        yield from _with_env(dirs.config("myapp"), {"HOME": "/home/ada"})
    ) == "/home/ada/.config/myapp"
    assert (
        yield from _with_env(dirs.config("myapp"), {"HOME": "/home/bob"})
    ) == "/home/bob/.config/myapp"


@testing.effect
def test_is_provided_by_a_layer():
    """UserDirectories / is provided by a layer"""
    config_dir = ud.UserDirectories().flat_map(lambda dirs: dirs.config("myapp"))
    assert (
        yield from _with_env(
            config_dir.pipe(fx.provide(ud.layer_platform("linux"))), {"HOME": "/home/ada"}
        )
    ) == "/home/ada/.config/myapp"

    def config(app_name: str) -> fx.Effect[str]:
        return fx.succeed(f"/tmp/{app_name}")

    custom = dataclasses.replace(ud.make(), config=config)
    assert (
        yield from config_dir.pipe(fx.provide(fx.layer.succeed(ud.UserDirectories, custom)))
    ) == "/tmp/myapp"
