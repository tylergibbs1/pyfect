import pyfect as fx
from pyfect import config, config_provider, redacted

provider = config_provider.from_unknown({"db": {"url": "postgres://db", "password": "hunter2"}})


@config.gen
def database():
    url = yield from config.string("url")
    password = yield from config.redacted("password")  # a Redacted[str]
    return url, password


# or_die: a config error at startup is fatal (a defect, out of the error type).
url, password = fx.run_sync(
    database.nested("db").pipe(fx.provide(config_provider.layer(provider))).or_die()
)
assert url == "postgres://db"
assert str(password) == "<redacted>"  # never printed by str, repr or loggers
assert redacted.value(password) == "hunter2"
