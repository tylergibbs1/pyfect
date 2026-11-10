import pyfect as fx
from pyfect import config_provider
from pyfect.persistence import user_directories
from pyfect.persistence.user_directories import UserDirectories


@fx.fn
def directories():
    dirs = yield from UserDirectories()
    return (yield from dirs.config("myapp")), (yield from dirs.cache("myapp"))


# The variables come from the ConfigProvider; here a fixed environment.
def on(platform: str, env: dict[str, str]) -> tuple[str, str]:
    program = directories().pipe(fx.provide(user_directories.layer_platform(platform)))
    environment = config_provider.layer(config_provider.from_env(env=env))
    return fx.run_blocking(program.pipe(fx.provide(environment)).or_die())


print(on("linux", {"HOME": "/home/ada"}))
print(on("linux", {"HOME": "/home/ada", "XDG_CONFIG_HOME": "/etc/ada"}))
print(on("darwin", {"HOME": "/Users/ada"}))
print(on("win32", {"APPDATA": "C:\\Users\\ada\\AppData\\Roaming", "USERPROFILE": "C:\\Users\\ada"}))

# The host's own directories: user_directories.layer (platform.layer doesn't include it).
config_dir, _ = fx.run_blocking(directories().pipe(fx.provide(user_directories.layer)).or_die())
assert config_dir.endswith("myapp")

missing = directories().pipe(fx.provide(user_directories.layer_platform("linux")))
error = fx.run_blocking(
    missing.flip()
    .or_die()
    .pipe(fx.provide(config_provider.layer(config_provider.from_env(env={}))))
)
print(error.reason.tag, "-", error.reason.description)
