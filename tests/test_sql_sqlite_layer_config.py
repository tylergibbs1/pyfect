"""``sqlite.layer_config``: the client's config read from the provider."""

from pathlib import Path

import pyfect as fx
from pyfect import config, config_provider, testing
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


@testing.effect
def test_reads_each_field_from_its_config(tmp_path: Path):
    provider = config_provider.from_unknown({"DATABASE_PATH": str(tmp_path / "app.db")})
    client_layer = sqlite.layer_config({"filename": config.string("DATABASE_PATH")})

    def body():
        sql = yield from SqlClient()
        return (yield from sql("SELECT 1 AS one"))

    rows = (
        yield from fx.gen(body)
        .pipe(fx.provide(client_layer))
        .pipe(fx.provide(config_provider.layer(provider)))
    )
    assert rows == [{"one": 1}]
    assert (tmp_path / "app.db").exists()


@testing.effect
def test_a_missing_field_fails_with_a_config_error():
    provider = config_provider.from_unknown({})
    client_layer = sqlite.layer_config({"filename": config.string("DATABASE_PATH")})

    error = (
        yield from SqlClient()
        .pipe(fx.provide(client_layer))
        .pipe(fx.provide(config_provider.layer(provider)))
        .flip()
    )
    assert isinstance(error, config.ConfigError)
