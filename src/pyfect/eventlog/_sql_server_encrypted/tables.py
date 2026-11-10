"""The tables of the SQL encrypted storage, per dialect.

Global: the remote id, session auth bindings, and the compaction stores,
buckets, activations and stages. Per store (named by a hash of its scope
under the prefix): ``T`` (batches), ``T_ids`` (entry ids with the sequence
each was first stored at) and ``T_snapshot`` (staged and committed
snapshot batches). Two instances can open one table at once, and
PostgreSQL and SQL Server can fail the loser of a concurrent create, so
creation retries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import LiteralString

from pyfect._core import Effect
from pyfect.effect import gen
from pyfect.sql.client import SqlClientService
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Fragment


@dataclass(frozen=True, slots=True)
class Types:
    """The column types of the compaction tables."""

    id: Fragment
    int: Fragment
    bigint: Fragment
    bytes: Fragment
    entry_id: Fragment
    iv: Fragment


def types_for(sql: SqlClientService) -> Types:
    literal = sql.literal
    return sql.on_dialect_or_else(
        pg=lambda: Types(
            literal("TEXT"),
            literal("INTEGER"),
            literal("BIGINT"),
            literal("BYTEA"),
            literal("BYTEA"),
            literal("BYTEA"),
        ),
        mysql=lambda: Types(
            literal("VARCHAR(36)"),
            literal("INT"),
            literal("BIGINT"),
            literal("LONGBLOB"),
            literal("BINARY(16)"),
            literal("BINARY(12)"),
        ),
        mssql=lambda: Types(
            literal("NVARCHAR(36)"),
            literal("INT"),
            literal("BIGINT"),
            literal("VARBINARY(MAX)"),
            literal("VARBINARY(16)"),
            literal("VARBINARY(12)"),
        ),
        or_else=lambda: Types(
            literal("TEXT"),
            literal("INTEGER"),
            literal("INTEGER"),
            literal("BLOB"),
            literal("BLOB"),
            literal("BLOB"),
        ),
    )


def create_table(
    sql: SqlClientService, name: str, columns: Fragment, indexes: Sequence[LiteralString] = ()
) -> Effect[None, SqlError]:
    """``CREATE TABLE`` unless it exists, with ``indexes`` named
    ``<name>_i<n>``."""
    table = sql.identifier(name)

    def mysql():
        definitions = [columns, *(sql("INDEX ({})", sql.literal(index)) for index in indexes)]
        yield from sql(
            "CREATE TABLE IF NOT EXISTS {} ({})", table, sql.join(", ", False)(definitions)
        )

    def mssql():
        yield from sql("IF OBJECT_ID({}, N'U') IS NULL CREATE TABLE {} ({})", name, table, columns)
        for i, index in enumerate(indexes):
            index_name = f"{name}_i{i}"
            yield from sql(
                "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = {} "
                "AND object_id = OBJECT_ID({})) CREATE INDEX {} ON {} ({})",
                index_name,
                name,
                sql.identifier(index_name),
                table,
                sql.literal(index),
            )

    def other():
        yield from sql("CREATE TABLE IF NOT EXISTS {} ({})", table, columns)
        for i, index in enumerate(indexes):
            yield from sql(
                "CREATE INDEX IF NOT EXISTS {} ON {} ({})",
                sql.identifier(f"{name}_i{i}"),
                table,
                sql.literal(index),
            )

    body = sql.on_dialect_or_else(mysql=lambda: mysql, mssql=lambda: mssql, or_else=lambda: other)
    return gen(body).retry(times=3)


def create_global_tables(
    sql: SqlClientService, prefix: str, remote_id_table: str
) -> Effect[None, SqlError]:
    remote_ids = sql.identifier(remote_id_table)
    bindings_table = f"{prefix}_session_auth_bindings"
    bindings = sql.identifier(bindings_table)
    types = types_for(sql)

    def body():
        if sql.dialect == "pg":
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (remote_id BYTEA PRIMARY KEY)", remote_ids
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (public_key TEXT PRIMARY KEY, "
                "signing_public_key BYTEA NOT NULL)",
                bindings,
            )
        elif sql.dialect == "mssql":
            yield from sql(
                "IF OBJECT_ID({}, N'U') IS NULL "
                "CREATE TABLE {} (remote_id VARBINARY(16) PRIMARY KEY)",
                remote_id_table,
                remote_ids,
            )
            yield from sql(
                "IF OBJECT_ID({}, N'U') IS NULL CREATE TABLE {} ("
                "public_key NVARCHAR(191) PRIMARY KEY, signing_public_key VARBINARY(32) NOT NULL)",
                bindings_table,
                bindings,
            )
        elif sql.dialect == "mysql":
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (remote_id BINARY(16) PRIMARY KEY)", remote_ids
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (public_key VARCHAR(191) PRIMARY KEY, "
                "signing_public_key BINARY(32) NOT NULL)",
                bindings,
            )
        else:
            yield from sql("CREATE TABLE IF NOT EXISTS {} (remote_id BLOB PRIMARY KEY)", remote_ids)
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (public_key TEXT PRIMARY KEY, "
                "signing_public_key BLOB NOT NULL)",
                bindings,
            )
        # One row per store, keyed by the scope hash its tables are named after.
        yield from create_table(
            sql,
            f"{prefix}_compaction_stores",
            sql(
                "scope {id} PRIMARY KEY, next_sequence {int} NOT NULL, "
                "active_activation {id} NOT NULL, active_batch_set {id} NULL, "
                "base_sequence {int} NOT NULL, active_kept_count {int} NOT NULL, "
                "no_op_at {int} NULL, no_op_count {int} NOT NULL, open_stage {id} NULL, "
                "next_sweep_at {bigint} NULL, sweep_lease_until {bigint} NULL, "
                "sweep_lease_owner {id} NULL, pruned_through {int} NOT NULL",
                id=types.id,
                int=types.int,
                bigint=types.bigint,
            ),
            ["next_sweep_at"],
        )
        # The highest last sequence stored in each storage-time hour.
        yield from create_table(
            sql,
            f"{prefix}_compaction_buckets",
            sql(
                "scope {id} NOT NULL, bucket_hour {bigint} NOT NULL, "
                "last_sequence {int} NOT NULL, PRIMARY KEY (scope, bucket_hour)",
                id=types.id,
                int=types.int,
                bigint=types.bigint,
            ),
        )
        # A null ``batch_set`` means the originals only. ``prunable_at`` is
        # set when the activation is superseded or withdrawn.
        yield from create_table(
            sql,
            f"{prefix}_compaction_activations",
            sql(
                "id {id} PRIMARY KEY, scope {id} NOT NULL, ordinal {int} NOT NULL, "
                "batch_set {id} NULL, base_sequence {int} NOT NULL, kept_count {int} NULL, "
                "previous {id} NULL, superseded_at {bigint} NULL, prunable_at {bigint} NULL, "
                "prune_started_at {bigint} NULL",
                id=types.id,
                int=types.int,
                bigint=types.bigint,
            ),
            ["scope, ordinal"],
        )
        # A stage's pending batch set is its own id. A committed stage's row
        # is deleted at commit; other stages go from ``open`` to ``closed``,
        # and the sweep deletes what they staged, then the row.
        yield from create_table(
            sql,
            f"{prefix}_compaction_stages",
            sql(
                "id {id} PRIMARY KEY, scope {id} NOT NULL, state {id} NOT NULL, "
                "pinned {id} NOT NULL, through_sequence {int} NOT NULL, "
                "expires_at {bigint} NOT NULL",
                id=types.id,
                int=types.int,
                bigint=types.bigint,
            ),
            ["scope, state", "state, expires_at"],
        )

    return gen(body)


def create_scope_tables(sql: SqlClientService, table: str) -> Effect[None, SqlError]:
    """``T`` and ``T_ids`` as every version of the storage creates them, and
    ``T_snapshot``, whose ``sequence`` and ``last_sequence`` stay null until
    commit."""
    table_sql = sql.identifier(table)
    ids_table = f"{table}_ids"
    ids_sql = sql.identifier(ids_table)
    index_sql = sql.identifier(f"{table}_last_sequence")
    types = types_for(sql)

    def legacy():
        if sql.dialect == "mssql":
            yield from sql(
                "IF OBJECT_ID({}, N'U') IS NULL CREATE TABLE {} (sequence INT PRIMARY KEY, "
                "last_sequence INT NOT NULL, iv VARBINARY(12) NOT NULL, "
                "entry_ids VARBINARY(MAX) NOT NULL, encrypted_batch VARBINARY(MAX) NOT NULL, "
                "INDEX {} NONCLUSTERED (last_sequence))",
                table,
                table_sql,
                index_sql,
            )
            yield from sql(
                "IF OBJECT_ID({}, N'U') IS NULL CREATE TABLE {} ("
                "entry_id VARBINARY(16) PRIMARY KEY, sequence INT NOT NULL)",
                ids_table,
                ids_sql,
            )
        elif sql.dialect == "mysql":
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (sequence INT PRIMARY KEY, "
                "last_sequence INT NOT NULL, iv BINARY(12) NOT NULL, "
                "entry_ids LONGBLOB NOT NULL, encrypted_batch LONGBLOB NOT NULL, "
                "INDEX (last_sequence))",
                table_sql,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (entry_id BINARY(16) PRIMARY KEY, "
                "sequence INT NOT NULL)",
                ids_sql,
            )
        elif sql.dialect == "pg":
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (sequence INTEGER PRIMARY KEY, "
                "last_sequence INTEGER NOT NULL, iv BYTEA NOT NULL, entry_ids BYTEA NOT NULL, "
                "encrypted_batch BYTEA NOT NULL)",
                table_sql,
            )
            yield from sql(
                "CREATE INDEX IF NOT EXISTS {} ON {} (last_sequence)", index_sql, table_sql
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (entry_id BYTEA PRIMARY KEY, "
                "sequence INTEGER NOT NULL)",
                ids_sql,
            )
        else:
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (sequence INTEGER PRIMARY KEY, "
                "last_sequence INTEGER NOT NULL, iv BLOB NOT NULL, entry_ids BLOB NOT NULL, "
                "encrypted_batch BLOB NOT NULL)",
                table_sql,
            )
            yield from sql(
                "CREATE INDEX IF NOT EXISTS {} ON {} (last_sequence)", index_sql, table_sql
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (entry_id BLOB PRIMARY KEY, "
                "sequence INTEGER NOT NULL)",
                ids_sql,
            )

    def body():
        yield from gen(legacy).retry(times=3)
        yield from create_table(
            sql,
            f"{table}_snapshot",
            sql(
                "batch_set {id} NOT NULL, batch_position {bigint} NOT NULL, "
                "sequence {int} NULL, last_sequence {int} NULL, entry_count {int} NOT NULL, "
                "iv {iv} NOT NULL, entry_ids {bytes} NOT NULL, encrypted_batch {bytes} NOT NULL, "
                "PRIMARY KEY (batch_set, batch_position)",
                id=types.id,
                int=types.int,
                bigint=types.bigint,
                iv=types.iv,
                bytes=types.bytes,
            ),
            ["batch_set, last_sequence"],
        )

    return gen(body)
