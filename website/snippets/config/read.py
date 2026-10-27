import pyfect as fx
from pyfect import config, config_provider


@config.gen
def server():
    host = yield from config.string("HOST").with_default("localhost")
    port = yield from config.port("PORT")
    debug = yield from config.boolean("DEBUG").with_default(False)
    return (host, port, debug)


# Configs read from CurrentConfigProvider: environment variables unless a layer
# installs another source (a .env file, a directory, nested dicts).
env = config_provider.layer(config_provider.from_env(env={"PORT": "8080", "DEBUG": "true"}))

# server is a Config[tuple[str, int, bool]] and an Effect failing with ConfigError.
# ConfigError is still in the type, so run_sync (which takes only effects that
# cannot fail) would be a type error: run_sync_exit returns the Exit instead.
assert fx.run_sync_exit(server.pipe(fx.provide(env))) == fx.Success(("localhost", 8080, True))

# Invalid data fails with a readable message, not a default.
bad = config_provider.layer(config_provider.from_env(env={"PORT": "99999"}))
exit = fx.run_sync_exit(server.pipe(fx.provide(bad)))
assert isinstance(exit, fx.Failure)
assert "Expected a value between 1 and 65535" in str(exit.cause.squash())
