"""``migrator.from_file_system`` on the live file system: the modules of a
real directory run in id order, and a module that cannot be imported fails
the run with an ``ImportError`` migration error."""

from pathlib import Path

import pyfect as fx
from pyfect import file_system, path, reactivity, testing
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.sql.migrator import MigrationError
from pyfect.sql.sqlite import migrator


def make_client(directory: Path):
    return sqlite.make(sqlite.SqliteClientConfig(filename=str(directory / "test.db"))).pipe(
        fx.provide(reactivity.layer)
    )


_CREATE = """
import pyfect as fx
from pyfect.sql.client import SqlClient

def _body():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")

default = fx.gen(_body)
"""

_ADD_EMAIL = """
import pyfect as fx
from pyfect.sql.client import SqlClient

def _body():
    sql = yield from SqlClient()
    yield from sql("ALTER TABLE users ADD COLUMN email TEXT")

default = fx.gen(_body)
"""


def _run(directory: Path, client: sqlite.SqliteClientService):
    return (
        migrator.run(loader=migrator.from_file_system(str(directory)))
        .pipe(fx.provide_service(SqlClient, client))
        .pipe(fx.provide(file_system.layer))
        .pipe(fx.provide(path.layer))
    )


@testing.effect
def test_runs_the_modules_of_a_directory_in_id_order(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0002_add_email.py").write_text(_ADD_EMAIL)
    (migrations / "0001_create_users.py").write_text(_CREATE)
    (migrations / "README.md").write_text("not a migration")
    client = yield from make_client(tmp_path)

    ran = yield from _run(migrations, client)
    again = yield from _run(migrations, client)
    columns = yield from client("SELECT name FROM pragma_table_info('users') ORDER BY cid")

    assert list(ran) == [(1, "create_users"), (2, "add_email")]
    assert list(again) == []
    assert [row["name"] for row in columns] == ["id", "name", "email"]


@testing.effect
def test_a_module_that_does_not_import_fails_with_an_import_error(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_broken.py").write_text("def oops(:\n")
    client = yield from make_client(tmp_path)

    error = yield from _run(migrations, client).flip()

    assert isinstance(error, MigrationError)
    assert error.kind == "ImportError"
    assert 'Could not import migration "1_broken"' in error.message
