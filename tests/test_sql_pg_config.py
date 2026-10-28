"""``pyfect.sql.pg.config``: settings are checked when built."""

import pytest

pytest.importorskip("psycopg")

from pyfect import redacted
from pyfect.effect import succeed, void
from pyfect.sql.pg import PgClientConfig, PgConnectionConfig, PgPoolConfig


def test_a_password_is_redacted_text_or_an_effect():
    PgConnectionConfig(password=redacted.make("secret"))
    PgConnectionConfig(password=succeed(redacted.make("secret")))
    with pytest.raises(TypeError, match="password"):
        PgConnectionConfig(password=lambda: redacted.make("secret"))  # pyright: ignore[reportArgumentType]


def test_on_acquire_is_an_effect():
    PgClientConfig(on_acquire=void)
    with pytest.raises(TypeError, match="on_acquire"):
        PgClientConfig(on_acquire=print)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match="on_acquire"):
        PgPoolConfig(on_acquire=print)  # pyright: ignore[reportArgumentType]


def test_pool_sizes_are_checked():
    with pytest.raises(ValueError, match="max_connections"):
        PgPoolConfig(min_connections=3, max_connections=2)
    with pytest.raises(ValueError, match="prepared_statement_cache_size"):
        PgPoolConfig(prepared_statement_cache_size=-1)
