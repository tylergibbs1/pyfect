import os

import pyfect as fx
from pyfect import platform, redacted
from pyfect.sql import SqlClient, pg
from pyfect.sql.pg import migrator


@fx.fn
def create_jobs():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE jobs (id serial PRIMARY KEY, name text NOT NULL)")


@fx.fn
def add_progress():
    sql = yield from SqlClient()
    # Braces are placeholders: a literal "{}" is written "{{}}".
    yield from sql("ALTER TABLE jobs ADD COLUMN progress jsonb NOT NULL DEFAULT '{{}}'")


loader = migrator.from_record({"1_create_jobs": create_jobs(), "2_add_progress": add_progress()})

database = pg.layer(pg.PgPoolConfig(url=redacted.make(os.environ["DATABASE_URL"])))
# Migrates when built, before anything else uses the database. With
# schema_directory="db", it also writes the schema there with pg_dump.
migrated = (
    migrator.layer(loader=loader)
    .pipe(fx.layer.provide_merge(database))
    .pipe(fx.layer.provide(platform.layer))  # pg_dump runs as a child process
)


@fx.fn
def program():
    sql = yield from SqlClient()
    print((yield from sql("SELECT migration_id, name FROM effect_sql_migrations")))
    columns = yield from sql(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'jobs' ORDER BY ordinal_position"
    )
    print([row["column_name"] for row in columns])


fx.run_main(program().pipe(fx.provide(migrated)))
