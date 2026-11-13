"""Message storage in a SQL database (Effect's ``SqlMessageStorage``).

Envelopes are rows of ``<prefix>_messages`` and replies rows of
``<prefix>_replies``, both keyed by their snowflakes. A request with a
primary key stores it in ``message_id`` (a SHA-256 digest when longer than
the 255-character column), which detects duplicates. ``unprocessed_messages``
claims the rows it returns by setting ``last_read``; a claim lapses after
ten minutes.

On MySQL and SQL Server the key columns (``message_id``, ``shard_id``,
``entity_type``, ``entity_id``) compare exactly, as on SQLite and
PostgreSQL (migration ``0004``, pyfect's): MySQL's in ``utf8mb4_0900_bin``,
SQL Server's in a ``BIN2`` collation, also comparing lengths where a
trailing space can occur (``persistence._sql_keys``); Effect leaves them in
the server's collation, which usually ignores case.
Python's integers are exact, so ids need no ``SafeIntegers``; SHA-256 comes
from ``hashlib`` (Effect reads a ``Digest`` service).
"""

from __future__ import annotations

import hashlib
from collections.abc import Generator, Mapping, Sequence
from typing import Any, Final, LiteralString, Never

from pyfect import _json_text
from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._js import js_length, text_encode
from pyfect.cause import Cause, Fail
from pyfect.cluster import snowflake as snowflake_
from pyfect.cluster._sql_keys import MSSQL_EXACT_TEXT, MYSQL_EXACT_TEXT, key_in
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.envelope import Encoded as EnvelopeEncoded
from pyfect.cluster.envelope import ShardIdEncoded
from pyfect.cluster.message_storage import (
    SAVE_SUCCESS,
    DuplicateEncoded,
    EncodedMessage,
    EncodedStorage,
    MessageStorage,
    MessageStorageService,
    SaveResultEncoded,
    make_encoded,
)
from pyfect.cluster.reply import ChunkEncoded, Encoded, WithExitEncoded
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.cluster.snowflake import Snowflake
from pyfect.effect import die, fail_cause, gen, succeed, suspend, void
from pyfect.persistence._sql_keys import key_equals, mssql_match
from pyfect.sql import migrator
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError, is_sql_error
from pyfect.sql.result import affected_rows
from pyfect.sql.statement import Fragment, Statement

_REQUEST, _ACK_CHUNK, _INTERRUPT = 0, 1, 2
_WITH_EXIT = 0
"""A reply's ``kind``: ``0`` for an exit, ``NULL`` for a chunk."""

_MESSAGE_ID_WIDTH = 255


def message_id_for_primary_key(primary_key: str) -> str:
    """The stored key: the primary key when it fits the column (in UTF-16
    code units, as Effect measures it), else its
    SHA-256 hex digest (a digest has no ``/``, a composed key always
    does, so the two never collide)."""
    if js_length(primary_key) <= _MESSAGE_ID_WIDTH:
        return primary_key
    return hashlib.sha256(text_encode(primary_key)).hexdigest()


def _shard_id_encoded(text: str) -> ShardIdEncoded:
    group, _, id = text.rpartition(":")
    return {"group": group, "id": int(id)}


def _address(row: Row) -> Any:
    return {
        "shardId": _shard_id_encoded(str(row["shard_id"])),
        "entityType": row["entity_type"],
        "entityId": row["entity_id"],
    }


def _str(value: object) -> str:
    return str(value)


def _reply_from_row(row: Row) -> Encoded:
    if row["kind"] is not None and int(str(row["kind"])) == _WITH_EXIT:
        exit_reply: WithExitEncoded = {
            "_tag": "WithExit",
            "id": _str(row["id"]),
            "requestId": _str(row["request_id"]),
            "exit": _parse(str(row["payload"])),
        }
        return exit_reply
    chunk: ChunkEncoded = {
        "_tag": "Chunk",
        "id": _str(row["id"]),
        "requestId": _str(row["request_id"]),
        "values": _parse(str(row["payload"])),
        "sequence": int(str(row["sequence"])),
    }
    return chunk


def _message_from_row(row: Row) -> EncodedMessage:
    kind = int(str(row["kind"]))
    if kind == _REQUEST:
        envelope: Any = {
            "_tag": "Request",
            "requestId": _str(row["id"]),
            "address": _address(row),
            "tag": row["tag"],
            "payload": _parse(str(row["payload"])),
            "headers": _parse(str(row["headers"])),
        }
        if row["trace_id"]:
            envelope["traceId"] = row["trace_id"]
            envelope["spanId"] = row["span_id"]
            envelope["sampled"] = bool(row["sampled"])
        last: Encoded | None = None
        if row["reply_reply_id"]:
            last = {
                "_tag": "Chunk",
                "id": _str(row["reply_reply_id"]),
                "requestId": _str(row["request_id"]),
                "sequence": int(str(row["reply_sequence"])),
                "values": _parse(str(row["reply_payload"])),
            }
        return EncodedMessage(envelope, last)
    if kind == _ACK_CHUNK:
        ack: Any = {
            "_tag": "AckChunk",
            "id": _str(row["id"]),
            "requestId": _str(row["request_id"]),
            "replyId": _str(row["reply_id"]),
            "address": _address(row),
        }
        return EncodedMessage(ack, None)
    interrupt: Any = {
        "_tag": "Interrupt",
        "id": _str(row["id"]),
        "requestId": _str(row["request_id"]),
        "address": _address(row),
    }
    return EncodedMessage(interrupt, None)


def _group_addresses(
    addresses: Sequence[EntityAddress],
) -> list[tuple[str, str, list[str]]]:
    """``(shard, entity type, entity ids)`` groups, in first-seen order."""
    groups: dict[tuple[str, str], list[str]] = {}
    for address in addresses:
        groups.setdefault((str(address.shard_id), address.entity_type), []).append(
            address.entity_id
        )
    return [(shard, entity_type, ids) for (shard, entity_type), ids in groups.items()]


class _Storage:
    """The ``EncodedStorage`` of one client."""

    def __init__(self, sql: SqlClientService, prefix: str) -> None:
        self.sql = sql
        self.messages = sql.identifier(f"{prefix}_messages")
        self.replies = sql.identifier(f"{prefix}_replies")
        self.supports_booleans: bool = sql.on_dialect_or_else(
            mssql=lambda: False, sqlite=lambda: False, or_else=lambda: True
        )
        self.message_id_enforces_width: bool = sql.on_dialect_or_else(
            mssql=lambda: True, mysql=lambda: True, pg=lambda: True, or_else=lambda: False
        )
        # SQLite ids read as text: drivers that return numbers would round
        self.ids_as_text: bool = sql.dialect == "sqlite"
        self.false = sql.literal("FALSE") if self.supports_booleans else sql.literal("0")
        self.true = sql.literal("TRUE") if self.supports_booleans else sql.literal("1")
        self.kind_ack_chunk = sql.literal("1")
        self.kind_interrupt = sql.literal("2")
        self.kind_with_exit = sql.literal("0")
        self.ten_minutes_ago: Fragment = sql.on_dialect_or_else(
            mssql=lambda: sql.literal("DATEADD(MINUTE, -10, GETDATE())"),
            mysql=lambda: sql.literal("NOW() - INTERVAL 10 MINUTE"),
            pg=lambda: sql.literal("NOW() - INTERVAL '10 minutes'"),
            or_else=lambda: sql.literal("DATETIME('now', '-10 minute')"),
        )
        self.now: Fragment = sql.on_dialect_or_else(
            pg=lambda: sql.literal("NOW()"),
            mysql=lambda: sql.literal("NOW()"),
            mssql=lambda: sql.literal("GETDATE()"),
            or_else=lambda: sql.literal("CURRENT_TIMESTAMP"),
        )
        self.for_update: Fragment = sql.on_dialect_or_else(
            mssql=lambda: sql.literal(""),
            sqlite=lambda: sql.literal(""),
            or_else=lambda: sql.literal("FOR UPDATE"),
        )
        self.update_lock: Fragment = sql.on_dialect_or_else(
            mssql=lambda: sql.literal("WITH (UPDLOCK)"), or_else=lambda: sql.literal("")
        )
        reply_join = (
            "r.kind as reply_kind, r.payload as reply_payload, r.sequence as reply_sequence"
        )
        if self.ids_as_text:
            message_columns = (
                f"{self._id_as('m.id', 'id')}, m.message_id, m.shard_id, m.entity_type, "
                "m.entity_id, m.kind, m.tag, m.payload, m.headers, m.trace_id, m.span_id, "
                f"m.sampled, m.processed, {self._id_as('m.request_id', 'request_id')}, "
                f"{self._id_as('m.reply_id', 'reply_id')}, "
                f"{self._id_as('m.last_reply_id', 'last_reply_id')}, m.last_read, m.deliver_at"
            )
        else:
            message_columns = "m.*"
        self.id_column = sql.unsafe(self._id_as("id", "id"))
        self.reply_columns = sql.unsafe(
            f"{self._id_as('id', 'id')}, kind, {self._id_as('request_id', 'request_id')}, "
            "payload, sequence"
        )
        self.duplicate_columns = sql.unsafe(
            f"{self._id_as('m.id', 'id')}, {self._id_as('r.id', 'reply_id')}, {reply_join}"
        )
        self.message_join_columns = sql.unsafe(
            f"{message_columns}, {self._id_as('r.id', 'reply_reply_id')}, {reply_join}"
        )

    def _id_as(self, column: str, alias: str) -> str:
        return f"CAST({column} AS TEXT) AS {alias}" if self.ids_as_text else f"{column} AS {alias}"

    def wrap_string(self, text: str) -> str:
        return f"N'{text}'" if self.sql.dialect == "mssql" else f"'{text}'"

    def shard_list(self, shard_ids: Sequence[str]) -> Statement[Any]:
        return self.sql.unsafe(",".join(self.wrap_string(s) for s in shard_ids))

    def may_have_legacy_row(self, primary_key: str) -> bool:
        """SQLite's ``message_id`` stored over-long keys as text before
        digests; those rows are read by the plain key too."""
        return not self.message_id_enforces_width and js_length(primary_key) > _MESSAGE_ID_WIDTH

    def sampled(self, sampled: bool | None) -> object:
        if sampled is None:
            return None
        return sampled if self.supports_booleans else int(sampled)

    def envelope_row(
        self, envelope: EnvelopeEncoded, message_id: str | None, deliver_at: int | None
    ) -> dict[str, object]:
        address = envelope["address"]
        shard = f"{address['shardId']['group']}:{address['shardId']['id']}"
        common: dict[str, object] = {
            "message_id": message_id,
            "shard_id": shard,
            "entity_type": address["entityType"],
            "entity_id": address["entityId"],
            "deliver_at": deliver_at,
        }
        match envelope["_tag"]:
            case "Request":
                return {
                    "id": envelope["requestId"],
                    **common,
                    "kind": _REQUEST,
                    "tag": envelope["tag"],
                    "payload": _json_text.stringify(envelope["payload"]),
                    "headers": _json_text.stringify(dict(envelope["headers"])),
                    "trace_id": envelope.get("traceId"),
                    "span_id": envelope.get("spanId"),
                    "sampled": self.sampled(envelope.get("sampled")),
                    "request_id": envelope["requestId"],
                    "reply_id": None,
                }
            case "AckChunk":
                return {
                    "id": envelope["id"],
                    **common,
                    "kind": _ACK_CHUNK,
                    "tag": None,
                    "payload": None,
                    "headers": None,
                    "trace_id": None,
                    "span_id": None,
                    "sampled": None,
                    "request_id": envelope["requestId"],
                    "reply_id": envelope["replyId"],
                }
            case "Interrupt":
                return {
                    "id": envelope["id"],
                    **common,
                    "kind": _INTERRUPT,
                    "tag": None,
                    "payload": None,
                    "headers": None,
                    "trace_id": None,
                    "span_id": None,
                    "sampled": None,
                    "request_id": envelope["requestId"],
                    "reply_id": None,
                }

    def select_by_message_id(self, message_id: str) -> Effect[Sequence[Row], SqlError]:
        return self.sql(
            "SELECT {} FROM {} m LEFT JOIN {} r ON r.id = m.last_reply_id WHERE {}",
            self.duplicate_columns,
            self.messages,
            self.replies,
            key_equals(self.sql, "m.message_id", message_id),
        )

    def insert_envelope(
        self, row: Mapping[str, object], message_id: str
    ) -> Effect[Sequence[Row], SqlError]:
        sql = self.sql

        def unless_inserted(inserted: Sequence[object]) -> Effect[Sequence[Row], SqlError]:
            return succeed([]) if inserted else self.select_by_message_id(message_id)

        if sql.dialect == "pg":
            return sql(
                "INSERT INTO {} {} ON CONFLICT (message_id) DO NOTHING RETURNING id",
                self.messages,
                sql.insert(row),
            ).flat_map(unless_inserted)
        if sql.dialect == "mysql":

            def affected(result: Any) -> Effect[Sequence[Row], SqlError]:
                if affected_rows(result) > 0:
                    return succeed([])
                return self.select_by_message_id(message_id)

            return sql("INSERT IGNORE INTO {} {}", self.messages, sql.insert(row)).raw.flat_map(
                affected
            )
        if sql.dialect == "mssql":
            return sql(
                "MERGE {} WITH (HOLDLOCK) AS target USING (SELECT {} as message_id) AS source "
                "ON " + mssql_match("message_id") + " WHEN NOT MATCHED THEN INSERT {} "
                "OUTPUT inserted.id;",
                self.messages,
                message_id,
                sql.insert(row),
            ).flat_map(unless_inserted)
        insert = sql("INSERT OR IGNORE INTO {} {}", self.messages, sql.insert(row))
        return sql.with_transaction(
            self.select_by_message_id(message_id).tap(lambda _: insert)
        ).retry(times=3)

    def address_filter(self, addresses: Sequence[EntityAddress], prefix: str) -> Fragment:
        sql = self.sql
        return sql.or_(
            [
                sql.and_(
                    [
                        sql(f"{prefix}shard_id = {{}}", shard),  # pyright: ignore[reportArgumentType]
                        key_equals(sql, f"{prefix}entity_type", entity_type),
                        key_in(sql, f"{prefix}entity_id", ids),
                    ]
                )
                for shard, entity_type, ids in _group_addresses(addresses)
            ]
        )

    def unprocessed_rows(
        self,
        shard_ids: Sequence[str],
        now: int,
        limit: int | None,
        addresses: Sequence[EntityAddress] | None,
    ) -> Effect[Sequence[Row], SqlError]:
        sql = self.sql
        address_filter = (
            sql.literal("")
            if addresses is None
            else sql("AND ({})", self.address_filter(addresses, "m."))
        )
        if limit is None:
            limit_fragment: Fragment = sql.literal("")
        elif sql.dialect == "mssql":
            limit_fragment = sql.unsafe(f"OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY")
        else:
            limit_fragment = sql.unsafe(f"LIMIT {int(limit)}")
        deliverable = sql.unsafe(str(now))
        if sql.dialect == "pg":
            return sql(
                "WITH messages AS ("
                "UPDATE {} m SET last_read = {} FROM ("
                "SELECT m.* FROM {} m WHERE m.shard_id IN ({}) {} "
                "AND NOT EXISTS (SELECT 1 FROM {} WHERE request_id = m.request_id "
                "AND (kind = {} OR acked = {})) "
                "AND m.processed = {} "
                "AND (m.last_read IS NULL OR m.last_read < {}) "
                "AND (m.deliver_at IS NULL OR m.deliver_at <= {}) "
                "ORDER BY m.rowid ASC {} FOR UPDATE"
                ") AS ids LEFT JOIN {} r ON r.id = ids.last_reply_id "
                "WHERE m.id = ids.id "
                "RETURNING ids.*, r.id as reply_reply_id, r.kind as reply_kind, "
                "r.payload as reply_payload, r.sequence as reply_sequence"
                ") SELECT * FROM messages ORDER BY rowid ASC",
                self.messages,
                self.now,
                self.messages,
                self.shard_list(shard_ids),
                address_filter,
                self.replies,
                self.kind_with_exit,
                self.false,
                self.false,
                self.ten_minutes_ago,
                deliverable,
                limit_fragment,
                self.replies,
            )
        select = sql(
            "SELECT {} FROM {} m {} LEFT JOIN {} r ON r.id = m.last_reply_id "
            "WHERE m.shard_id IN ({}) {} "
            "AND NOT EXISTS (SELECT 1 FROM {} WHERE request_id = m.request_id "
            "AND (kind = {} OR acked = {})) "
            "AND processed = {} "
            "AND (m.last_read IS NULL OR m.last_read < {}) "
            "AND (m.deliver_at IS NULL OR m.deliver_at <= {}) "
            "ORDER BY m.rowid ASC {} {}",
            self.message_join_columns,
            self.messages,
            self.update_lock,
            self.replies,
            self.shard_list(shard_ids),
            address_filter,
            self.replies,
            self.kind_with_exit,
            self.false,
            self.false,
            self.ten_minutes_ago,
            deliverable,
            limit_fragment,
            self.for_update,
        ).unprepared

        def claim(rows: Sequence[Row]) -> Effect[object, SqlError]:
            if not rows:
                return void
            ids = sql.unsafe(",".join(str(row["id"]) for row in rows))
            return sql(
                "UPDATE {} SET last_read = {} WHERE id IN ({})", self.messages, self.now, ids
            ).unprepared

        return sql.with_transaction(select.tap(claim))

    def reset_unprocessed(self, filter: Fragment) -> Effect[object, SqlError]:
        sql = self.sql
        if sql.dialect == "pg":
            # the claim query's lock order, so resets cannot deadlock with it
            return sql(
                "WITH messages AS (SELECT id FROM {} WHERE processed = {} AND {} "
                "ORDER BY rowid ASC FOR UPDATE) "
                "UPDATE {} SET last_read = NULL WHERE id IN (SELECT id FROM messages)",
                self.messages,
                self.false,
                filter,
                self.messages,
            )
        return sql(
            "UPDATE {} SET last_read = NULL WHERE processed = {} AND {}",
            self.messages,
            self.false,
            filter,
        )

    # --- EncodedStorage ---------------------------------------------------------------

    def save_envelope(
        self, envelope: EnvelopeEncoded, primary_key: str | None, deliver_at: int | None, /
    ) -> Effect[SaveResultEncoded, PersistenceError]:
        sql = self.sql

        def insert() -> Effect[Sequence[Row], SqlError]:
            if primary_key is not None:
                message_id = message_id_for_primary_key(primary_key)
                row = self.envelope_row(envelope, message_id, deliver_at)
                if not self.may_have_legacy_row(primary_key):
                    return self.insert_envelope(row, message_id)
                return self.select_by_message_id(primary_key).flat_map(
                    lambda rows: succeed(rows) if rows else self.insert_envelope(row, message_id)
                )
            row = self.envelope_row(envelope, None, deliver_at)
            plain = sql("INSERT INTO {} {}", self.messages, sql.insert(row)).unprepared.as_(
                list[Row]()
            )
            if envelope["_tag"] != "AckChunk":
                return plain
            return sql.with_transaction(
                sql(
                    "UPDATE {} SET acked = {} WHERE id = {}",
                    self.replies,
                    self.true,
                    envelope["replyId"],
                )
                .flat_map(
                    lambda _: sql(
                        "UPDATE {} SET processed = {} WHERE processed = {} AND request_id = {} "
                        "AND kind = {}",
                        self.messages,
                        self.true,
                        self.false,
                        envelope["requestId"],
                        self.kind_ack_chunk,
                    )
                )
                .flat_map(lambda _: plain)
            )

        def result(rows: Sequence[Row]) -> SaveResultEncoded:
            if not rows:
                return SAVE_SUCCESS
            row = rows[0]
            last: Encoded | None = None
            if row["reply_id"]:
                kind = row["reply_kind"]
                if kind is not None and int(str(kind)) == _WITH_EXIT:
                    last = {
                        "_tag": "WithExit",
                        "id": _str(row["reply_id"]),
                        "requestId": _str(row["id"]),
                        "exit": _parse(str(row["reply_payload"])),
                    }
                else:
                    last = {
                        "_tag": "Chunk",
                        "id": _str(row["reply_id"]),
                        "requestId": _str(row["id"]),
                        "sequence": int(str(row["reply_sequence"])),
                        "values": _parse(str(row["reply_payload"])),
                    }
            return DuplicateEncoded(
                original_id=Snowflake(int(str(row["id"]))), last_received_reply=last
            )

        return _refail(suspend(insert).map(result))

    def save_reply(self, reply: Encoded, /) -> Effect[None, PersistenceError]:
        sql = self.sql

        def run() -> Effect[object, SqlError]:
            if reply["_tag"] == "WithExit":
                kind: object = _WITH_EXIT
                payload = _json_text.stringify(reply["exit"])
                sequence: object = None
                update = sql(
                    "UPDATE {} SET processed = {}, last_reply_id = {} WHERE request_id = {}",
                    self.messages,
                    self.true,
                    reply["id"],
                    reply["requestId"],
                )
            else:
                kind = None
                payload = _json_text.stringify(list(reply["values"]))
                sequence = reply["sequence"]
                update = sql(
                    "UPDATE {} SET last_reply_id = {} WHERE id = {}",
                    self.messages,
                    reply["id"],
                    reply["requestId"],
                )
            row = {
                "id": reply["id"],
                "kind": kind,
                "request_id": reply["requestId"],
                "payload": payload,
                "sequence": sequence,
            }
            insert = sql("INSERT INTO {} {}", self.replies, sql.insert(row))
            return sql.with_transaction(update.unprepared.flat_map(lambda _: insert))

        return _refail(suspend(run).as_void())

    def clear_replies(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[None, PersistenceError]:
        sql = self.sql
        id = str(request_id)

        def body() -> Generator[Effect[Any, Any, Any], Any]:
            if expected_reply_id is None:
                yield from sql(
                    "DELETE FROM {} WHERE request_id = {} AND kind = 0", self.replies, id
                )
                yield from sql(
                    "DELETE FROM {} WHERE request_id = {} AND kind = {}",
                    self.messages,
                    id,
                    self.kind_interrupt,
                )
                yield from sql(
                    "UPDATE {} SET processed = {}, last_reply_id = NULL, last_read = NULL "
                    "WHERE request_id = {}",
                    self.messages,
                    self.false,
                    id,
                )
                return
            expected = str(expected_reply_id)
            # checked here, at the storage boundary, not at an earlier read
            yield from sql(
                "DELETE FROM {} WHERE request_id = {} AND kind = 0 "
                "AND EXISTS (SELECT 1 FROM {} WHERE id = {} AND last_reply_id = {})",
                self.replies,
                id,
                self.messages,
                id,
                expected,
            )
            yield from sql(
                "UPDATE {} SET processed = {}, last_reply_id = NULL, last_read = NULL "
                "WHERE request_id = {} AND last_reply_id = {}",
                self.messages,
                self.false,
                id,
                expected,
            )

        return _refail(sql.with_transaction(gen(body)))

    def request_id_for_primary_key(
        self, primary_key: str, /
    ) -> Effect[Snowflake | None, PersistenceError]:
        sql = self.sql

        def select(key: str) -> Effect[Sequence[Row], SqlError]:
            return sql(
                "SELECT {} FROM {} WHERE {}",
                self.id_column,
                self.messages,
                key_equals(sql, "message_id", key),
            )

        def legacy(rows: Sequence[Row]) -> Effect[Sequence[Row], SqlError]:
            if not rows and self.may_have_legacy_row(primary_key):
                return select(primary_key)
            return succeed(rows)

        return _refail(
            select(message_id_for_primary_key(primary_key))
            .flat_map(legacy)
            .map(lambda rows: Snowflake(int(str(rows[0]["id"]))) if rows else None)
        )

    def replies_for(self, request_ids: Sequence[str], /) -> Effect[list[Encoded], PersistenceError]:
        # exits, and chunks not acknowledged yet
        sql = self.sql
        return _refail(
            sql(
                "SELECT {} FROM {} WHERE request_id IN ({}) "
                "AND (kind = {} OR (kind IS NULL AND acked = {})) ORDER BY rowid ASC",
                self.reply_columns,
                self.replies,
                sql.unsafe(",".join(str(int(i)) for i in request_ids)),
                self.kind_with_exit,
                self.false,
            ).unprepared.map(lambda rows: [_reply_from_row(r) for r in rows])
        )

    def replies_for_unfiltered(
        self, request_ids: Sequence[str], /
    ) -> Effect[list[Encoded], PersistenceError]:
        sql = self.sql
        return _refail(
            sql(
                "SELECT {} FROM {} WHERE request_id IN ({}) ORDER BY rowid ASC",
                self.reply_columns,
                self.replies,
                sql.unsafe(",".join(str(int(i)) for i in request_ids)),
            ).unprepared.map(lambda rows: [_reply_from_row(r) for r in rows])
        )

    def unprocessed_messages(
        self,
        shard_ids: Sequence[str],
        now: int,
        /,
        *,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> Effect[list[EncodedMessage], PersistenceError]:
        if addresses is not None and len(addresses) == 0:
            return succeed([])
        return _refail(
            self.unprocessed_rows(shard_ids, now, limit, addresses).map(
                lambda rows: [_message_from_row(r) for r in rows]
            )
        )

    def unprocessed_messages_by_id(
        self, message_ids: Sequence[Snowflake], now: int, /
    ) -> Effect[list[EncodedMessage], PersistenceError]:
        sql = self.sql
        return _refail(
            sql(
                "SELECT {} FROM {} m LEFT JOIN {} r ON r.id = m.last_reply_id "
                "WHERE m.id IN ({}) "
                "AND NOT EXISTS (SELECT 1 FROM {} WHERE request_id = m.request_id "
                "AND (kind = {} OR acked = {})) "
                "AND m.processed = {} "
                "AND (m.deliver_at IS NULL OR m.deliver_at <= {}) "
                "ORDER BY m.rowid ASC",
                self.message_join_columns,
                self.messages,
                self.replies,
                sql.unsafe(",".join(str(int(i)) for i in message_ids)),
                self.replies,
                self.kind_with_exit,
                self.false,
                self.false,
                sql.unsafe(str(now)),
            ).unprepared.map(lambda rows: [_message_from_row(r) for r in rows])
        )

    def reset_requests(self, request_ids: Sequence[Snowflake], /) -> Effect[None, PersistenceError]:
        if not request_ids:
            return void
        sql = self.sql
        return _refail(
            sql(
                "UPDATE {} SET last_read = NULL WHERE processed = {} AND {}",
                self.messages,
                self.false,
                sql.in_("id", [str(i) for i in request_ids]),
            ).as_void()
        )

    def reset_addresses(
        self, addresses: Sequence[EntityAddress], /
    ) -> Effect[None, PersistenceError]:
        if not addresses:
            return void
        filter = self.sql("({})", self.address_filter(addresses, ""))
        return _refail(self.reset_unprocessed(filter).as_void())

    def clear_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        sql = self.sql
        entity = sql.and_(
            [
                key_equals(sql, "entity_type", address.entity_type),
                key_equals(sql, "entity_id", address.entity_id),
            ]
        )
        replies = sql(
            "DELETE FROM {} WHERE request_id IN (SELECT id FROM {} WHERE {})",
            self.replies,
            self.messages,
            entity,
        )
        messages = sql("DELETE FROM {} WHERE {}", self.messages, entity)
        return _refail(sql.with_transaction(replies.flat_map(lambda _: messages)).as_void())

    def reset_shards(self, shard_ids: Sequence[str], /) -> Effect[None, PersistenceError]:
        filter = self.sql("shard_id IN ({})", self.shard_list(shard_ids))
        return _refail(self.reset_unprocessed(filter).as_void())

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        require_effect(effect, "effect")

        def defect(cause: Cause[Any]) -> Effect[A, E, R]:
            found = cause.find_recoverable_error()
            if isinstance(found, Fail) and is_sql_error(found.error):
                return die(found.error)
            return fail_cause(found if not isinstance(found, Fail) else cause)

        return self.sql.with_transaction(effect).catch_cause(defect)


def _refail[A](effect: Effect[A, Any]) -> Effect[A, PersistenceError]:
    return PersistenceError.refail(effect).with_tracer_enabled(False)


def make_encoded_storage(*, prefix: str = "cluster") -> Effect[EncodedStorage, Never, SqlClient]:
    """The driver on the tables of ``prefix`` (already migrated)."""
    return SqlClient().map(lambda sql: _Storage(sql.without_transforms(), prefix))


def make(
    *, prefix: str = "cluster"
) -> Effect[MessageStorageService, Never, SqlClient | snowflake_.Generator]:
    """Run the migrations, then a message storage on the tables."""
    return (
        run_migrations(prefix=prefix)
        .flat_map(lambda _: make_encoded_storage(prefix=prefix))
        .flat_map(make_encoded)
    )


def _create_messages(sql: SqlClientService, table: str) -> Effect[object, SqlError]:
    messages = sql.identifier(table)
    return sql.on_dialect_or_else(
        mssql=lambda: sql(
            "IF OBJECT_ID(N'{}', N'U') IS NULL CREATE TABLE {} ("
            "id BIGINT PRIMARY KEY, rowid BIGINT IDENTITY(1,1), message_id VARCHAR(255), "
            "shard_id VARCHAR(50) NOT NULL, entity_type VARCHAR(150) NOT NULL, "
            "entity_id VARCHAR(255) NOT NULL, kind INT NOT NULL, tag VARCHAR(50), "
            "payload NVARCHAR(MAX), headers NVARCHAR(MAX), trace_id VARCHAR(32), "
            "span_id VARCHAR(16), sampled BIT, processed BIT NOT NULL DEFAULT 0, "
            "request_id BIGINT NOT NULL, reply_id BIGINT, last_reply_id BIGINT, "
            "last_read DATETIME, deliver_at BIGINT, "
            "INDEX {} UNIQUE (message_id) WHERE message_id IS NOT NULL)",
            messages,
            messages,
            sql.identifier(f"{table}_message_id_idx"),
        ),
        mysql=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "id BIGINT NOT NULL, rowid BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
            "message_id VARCHAR(255), shard_id VARCHAR(50) NOT NULL, "
            "entity_type VARCHAR(150) NOT NULL, entity_id VARCHAR(255) NOT NULL, "
            "kind INT NOT NULL, tag VARCHAR(50), payload TEXT, headers TEXT, "
            "trace_id VARCHAR(32), span_id VARCHAR(16), sampled BOOLEAN, "
            "processed BOOLEAN NOT NULL DEFAULT FALSE, request_id BIGINT NOT NULL, "
            "reply_id BIGINT, last_reply_id BIGINT, last_read DATETIME, deliver_at BIGINT, "
            "UNIQUE (id), UNIQUE (message_id))",
            messages,
        ),
        pg=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "id BIGINT PRIMARY KEY, rowid BIGSERIAL, message_id VARCHAR(255), "
            "shard_id VARCHAR(50) NOT NULL, entity_type VARCHAR(150) NOT NULL, "
            "entity_id VARCHAR(255) NOT NULL, kind INT NOT NULL, tag VARCHAR(50), "
            "payload TEXT, headers TEXT, trace_id VARCHAR(32), span_id VARCHAR(16), "
            "sampled BOOLEAN, processed BOOLEAN NOT NULL DEFAULT FALSE, "
            "request_id BIGINT NOT NULL, reply_id BIGINT, last_reply_id BIGINT, "
            "last_read TIMESTAMP, deliver_at BIGINT, UNIQUE (message_id))",
            messages,
        ),
        or_else=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "id INTEGER PRIMARY KEY, message_id TEXT, shard_id TEXT NOT NULL, "
            "entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, kind INTEGER NOT NULL, "
            "tag TEXT, payload TEXT, headers TEXT, trace_id TEXT, span_id TEXT, "
            "sampled BOOLEAN, processed BOOLEAN NOT NULL DEFAULT FALSE, "
            "request_id INTEGER NOT NULL, reply_id INTEGER, last_reply_id INTEGER, "
            "last_read TEXT, deliver_at INTEGER, UNIQUE (message_id))",
            messages,
        ),
    )


def _create_replies(sql: SqlClientService, table: str) -> Effect[object, SqlError]:
    replies = sql.identifier(table)
    return sql.on_dialect_or_else(
        mssql=lambda: sql(
            "IF OBJECT_ID(N'{}', N'U') IS NULL CREATE TABLE {} ("
            "id BIGINT PRIMARY KEY, rowid BIGINT IDENTITY(1,1), kind INT, "
            "request_id BIGINT NOT NULL, payload NVARCHAR(MAX) NOT NULL, sequence INT, "
            "acked BIT NOT NULL DEFAULT 0, "
            "INDEX {} UNIQUE (request_id, kind) WHERE kind IS NOT NULL, "
            "INDEX {} UNIQUE (request_id, sequence) WHERE sequence IS NOT NULL)",
            replies,
            replies,
            sql.identifier(f"{table}_one_exit"),
            sql.identifier(f"{table}_sequence"),
        ),
        mysql=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "id BIGINT NOT NULL, rowid BIGINT AUTO_INCREMENT PRIMARY KEY, kind INT, "
            "request_id BIGINT NOT NULL, payload TEXT NOT NULL, sequence INT, "
            "acked BOOLEAN NOT NULL DEFAULT FALSE, UNIQUE (id), UNIQUE (request_id, kind), "
            "UNIQUE (request_id, sequence))",
            replies,
        ),
        pg=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "id BIGINT PRIMARY KEY, rowid BIGSERIAL, kind INT, request_id BIGINT NOT NULL, "
            "payload TEXT NOT NULL, sequence INT, acked BOOLEAN NOT NULL DEFAULT FALSE, "
            "UNIQUE (request_id, kind), UNIQUE (request_id, sequence))",
            replies,
        ),
        or_else=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "id INTEGER PRIMARY KEY, kind INTEGER, request_id INTEGER NOT NULL, "
            "payload TEXT NOT NULL, sequence INTEGER, acked BOOLEAN NOT NULL DEFAULT FALSE, "
            "UNIQUE (request_id, kind), UNIQUE (request_id, sequence))",
            replies,
        ),
    )


def _index(sql: SqlClientService, name: str, table: str, columns: str) -> Effect[object, SqlError]:
    index = sql.identifier(name)
    target = sql.identifier(table)
    cols = sql.unsafe(columns)
    return sql.on_dialect_or_else(
        mssql=lambda: sql(
            "IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = {}) CREATE INDEX {} ON {} ({})",
            name,
            index,
            target,
            cols,
        ),
        # MySQL has no IF NOT EXISTS for indexes: an existing one fails
        mysql=lambda: sql("CREATE INDEX {} ON {} ({})", index, target, cols).unprepared.ignore(
            log=False
        ),
        or_else=lambda: sql("CREATE INDEX IF NOT EXISTS {} ON {} ({})", index, target, cols),
    )


_EXACT_COLUMNS: Final[tuple[tuple[LiteralString, LiteralString, LiteralString], ...]] = (
    ("message_id", "255", "NULL"),
    ("shard_id", "50", "NOT NULL"),
    ("entity_type", "150", "NOT NULL"),
    ("entity_id", "255", "NOT NULL"),
)


def _exact_keys_mysql(sql: SqlClientService, table: str) -> Effect[object, SqlError]:
    columns = ", ".join(
        f"MODIFY {name} VARCHAR({width}) {MYSQL_EXACT_TEXT} {null}"
        for name, width, null in _EXACT_COLUMNS
    )
    return sql("ALTER TABLE {} " + columns, sql.identifier(table))


def _exact_keys_mssql(sql: SqlClientService, table: str) -> Effect[object, SqlError]:
    """``NVARCHAR`` in a ``BIN2`` collation; ``message_id``'s length is in
    its unique index, which ignores trailing spaces under every collation.
    The indexes on the columns are dropped first: a column in an index
    cannot change."""
    messages = sql.identifier(table)
    message_id_index = sql.identifier(f"{table}_message_id_idx")
    shard_index = sql.identifier(f"{table}_shard_idx")

    def body() -> Generator[Effect[Any, Any, Any], Any]:
        yield from sql("DROP INDEX {} ON {}", message_id_index, messages)
        yield from sql("DROP INDEX {} ON {}", shard_index, messages)
        for name, width, null in _EXACT_COLUMNS:
            yield from sql(
                "ALTER TABLE {} ALTER COLUMN {} " + f"NVARCHAR({width}) {MSSQL_EXACT_TEXT} {null}",
                messages,
                sql.identifier(name),
            )
        yield from sql("ALTER TABLE {} ADD message_id_length AS DATALENGTH(message_id)", messages)
        yield from sql(
            "CREATE UNIQUE INDEX {} ON {} (message_id, message_id_length) "
            "WHERE message_id IS NOT NULL",
            message_id_index,
            messages,
        )
        yield from sql(
            "CREATE INDEX {} ON {} (shard_id, processed, last_read, deliver_at)",
            shard_index,
            messages,
        )

    return gen(body)


def migrations(*, prefix: str = "cluster") -> migrator.Loader:
    """The message tables' migrations: ``0001`` to ``0003`` are Effect's,
    ``0004`` is pyfect's. PostgreSQL DDL is serialized by the migrator;
    errors propagate (a retry in an aborted transaction cannot succeed).
    Deployed databases have run the earlier migrations: a change to the
    schema is a new one, never an edit of an old one."""
    messages_table = f"{prefix}_messages"
    replies_table = f"{prefix}_replies"

    def create_tables() -> Generator[Effect[Any, Any, Any], Any]:
        sql = (yield from SqlClient()).without_transforms()
        yield from _create_messages(sql, messages_table)
        yield from _index(
            sql,
            f"{messages_table}_shard_idx",
            messages_table,
            "shard_id, processed, last_read, deliver_at",
        )
        yield from _index(sql, f"{messages_table}_request_id_idx", messages_table, "request_id")
        yield from _create_replies(sql, replies_table)
        yield from _index(
            sql, f"{replies_table}_request_lookup_idx", replies_table, "request_id, kind, acked"
        )

    def entity_type_size() -> Generator[Effect[Any, Any, Any], Any]:
        sql = (yield from SqlClient()).without_transforms()
        messages = sql.identifier(messages_table)
        yield from sql.on_dialect_or_else(
            mssql=lambda: sql(
                "ALTER TABLE {} ALTER COLUMN entity_type VARCHAR(150) NOT NULL;", messages
            ),
            mysql=lambda: sql(
                "ALTER TABLE {} MODIFY entity_type VARCHAR(150) NOT NULL;", messages
            ).unprepared.ignore(log=False),
            pg=lambda: sql("ALTER TABLE {} ALTER COLUMN entity_type TYPE VARCHAR(150);", messages),
            or_else=lambda: void,
        )

    def pg_rowid_index() -> Generator[Effect[Any, Any, Any], Any]:
        sql = (yield from SqlClient()).without_transforms()
        yield from sql.on_dialect_or_else(
            pg=lambda: _index(sql, f"{messages_table}_rowid_idx", messages_table, "rowid"),
            or_else=lambda: void,
        )

    def exact_keys() -> Generator[Effect[Any, Any, Any], Any]:
        sql = (yield from SqlClient()).without_transforms()
        yield from sql.on_dialect_or_else(
            mysql=lambda: _exact_keys_mysql(sql, messages_table),
            mssql=lambda: _exact_keys_mssql(sql, messages_table),
            or_else=lambda: void,
        )

    return migrator.from_record(
        {
            "0001_create_tables": gen(create_tables),
            "0002_entity_type_size": gen(entity_type_size),
            "0003_pg_messages_rowid_index": gen(pg_rowid_index),
            "0004_exact_keys": gen(exact_keys),
        }
    )


def run_migrations(*, prefix: str = "cluster") -> Effect[None, Never, SqlClient]:
    """Run the message migrations; a failure is a defect."""
    return (
        migrator.make()(loader=migrations(prefix=prefix), table=f"{prefix}_migrations")
        .as_void()
        .or_die()
    )


def layer_migrations(*, prefix: str = "cluster") -> layer_.Layer[Never, Never, SqlClient]:
    return layer_.effect_discard(run_migrations(prefix=prefix))


def layer_storage(
    *, prefix: str = "cluster"
) -> layer_.Layer[MessageStorage, Never, SqlClient | ShardingConfig]:
    """Message storage on migrated tables (with its own snowflake
    generator)."""
    return layer_.effect(
        MessageStorage, make_encoded_storage(prefix=prefix).flat_map(make_encoded)
    ).pipe(layer_.provide(snowflake_.layer_generator))


def layer_with(
    *, prefix: str = "cluster"
) -> layer_.Layer[MessageStorage, Never, SqlClient | ShardingConfig]:
    """``layer_storage`` after the migrations."""
    return layer_storage(prefix=prefix).pipe(layer_.provide(layer_migrations(prefix=prefix)))


layer: layer_.Layer[MessageStorage, Never, SqlClient | ShardingConfig] = layer_with()
"""``MessageStorage`` on the ``SqlClient`` in tables prefixed ``cluster``, after their
migrations (``layer_with()``)."""

__all__ = [
    "layer",
    "layer_migrations",
    "layer_storage",
    "layer_with",
    "make",
    "make_encoded_storage",
    "message_id_for_primary_key",
    "migrations",
    "run_migrations",
]


def _parse(text: str) -> Any:
    """A stored JSON column (written by ``_json_text.stringify``)."""
    return _json_text.parse(text)
