"""On MySQL and SQL Server the SQL cluster storages compare entity ids,
entity types, primary keys, shard ids and runner addresses exactly, as on
SQLite and PostgreSQL (GitHub issue #1).

Both servers' default collations (``utf8mb4_0900_ai_ci``, ``*_CI_AS``)
ignore case, and MySQL's also accents; every SQL Server collation and
MySQL's ``PAD SPACE`` ones ignore trailing spaces in ``=`` and in unique
indexes, and MySQL's named locks ignore case. Keys differing only in one
of these were one key: a request to ``alice`` was dropped as a duplicate
of one to ``Alice``, clearing one entity deleted the other's messages, and
two shard groups or runner addresses shared their locks. Shard ids
(``group:N``) and runner addresses (``host:port``) end in digits, so only
entity ids, entity types and primary keys can differ in trailing spaces.
Run on the session's MySQL (``mysql:lts``) and SQL Server (Azure SQL Edge
on ARM) containers; skipped without Docker.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Generator, Sequence
from dataclasses import replace
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import entity_address, envelope, runner, runner_address, shard_id, snowflake
from pyfect.cluster import sharding_config as sharding_config_
from pyfect.cluster import sql_message_storage as SqlMessageStorage
from pyfect.cluster import sql_runner_storage as SqlRunnerStorage
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.message_storage import MessageStorageService, SaveSuccess, make_encoded
from pyfect.cluster.runner_storage import RunnerStorageService
from pyfect.cluster.sharding_config import DEFAULTS, ShardingConfig
from pyfect.cluster.snowflake import Generator as SnowflakeGenerator
from pyfect.context import Context
from pyfect.rpc import make as make_rpc
from pyfect.sql import SqlClient, migrator

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")

CASE_AND_ACCENTS = {
    "case": ("alice", "Alice"),
    "accents": ("resume", "résumé"),
}
VARIANTS = {**CASE_AND_ACCENTS, "trailing spaces": ("alice", "alice ")}

# each server's default database, and one whose default collation ignores
# what the server's default does not: MySQL's ``utf8mb4_0900_ai_ci`` is
# ``NO PAD``, so ``utf8mb4_general_ci`` (``PAD SPACE``) adds trailing spaces;
# SQL Server's ``SQL_Latin1_General_CP1_CI_AS`` keeps accents, which
# ``Latin1_General_100_CI_AI`` ignores
SERVERS = {
    "mysql": None,
    "mysql-pad-space": "utf8mb4_general_ci",
    "mssql": None,
    "mssql-ci-ai": "Latin1_General_100_CI_AI",
}

_prefixes = itertools.count()


def _prefix() -> str:
    return f"xk_{os.getpid()}_{next(_prefixes)}"


def _mysql(request: pytest.FixtureRequest, collation: str | None) -> fx.Layer[Any, Any]:
    pytest.importorskip("asyncmy")
    from pyfect import redacted
    from pyfect.sql import mysql

    from ._mysql import MysqlServer
    from ._mysql import query_now as mysql_query

    server: MysqlServer = request.getfixturevalue("mysql_server")
    if collation is None:
        return mysql.layer(mysql.MysqlClientConfig(url=server.url))
    database = f"exact_{collation}"
    mysql_query(
        f"CREATE DATABASE IF NOT EXISTS {database} CHARACTER SET utf8mb4 COLLATE {collation}",
        root=True,
    )
    url = f"mysql://root:root@{server.host}:{server.port}/{database}"
    return mysql.layer(mysql.MysqlClientConfig(url=redacted.make(url)))


def _mssql(request: pytest.FixtureRequest, collation: str | None) -> fx.Layer[Any, Any]:
    pytest.importorskip("pytds")
    from pyfect.sql import mssql

    from ._mssql import MssqlServer
    from ._mssql import query_now as mssql_query

    server: MssqlServer = request.getfixturevalue("mssql_server")
    if collation is None:
        return mssql.layer(server.config())
    database = f"exact_{collation}"
    mssql_query(
        f"IF DB_ID('{database}') IS NULL CREATE DATABASE {database} COLLATE {collation}",
        database="master",
    )
    return mssql.layer(server.config(database=database))


@pytest.fixture(params=sorted(SERVERS))
def client(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    name: str = request.param
    collation = SERVERS[name]
    return _mysql(request, collation) if name.startswith("mysql") else _mssql(request, collation)


def _settings(**changes: Any) -> fx.Layer[ShardingConfig, Any]:
    return sharding_config_.layer(replace(DEFAULTS, **changes))


def _run(client: fx.Layer[Any, Any], body: Any, **settings: Any) -> Any:
    program = testing.with_live(fx.scoped(fx.gen(body)))
    return testing.run_test(
        program.pipe(fx.provide(snowflake.layer_generator))
        .pipe(fx.provide(_settings(**settings)))
        .pipe(fx.provide(client))
        .or_die()
    )


class KeyPayload(S.Class):
    id: str

    def primary_key(self) -> str:
        return self.id


KeyRpc = make_rpc("KeyRpc", payload=KeyPayload)


def _address(
    *, entity_id: str = "user", entity_type: str = "User", group: str = "default"
) -> EntityAddress:
    return entity_address.make(
        shard_id=shard_id.make(group, 1),
        entity_type=EntityType(entity_type),
        entity_id=EntityId(entity_id),
    )


def _request(
    address: EntityAddress, key: str = "1"
) -> fx.Effect[OutgoingRequest, Any, SnowflakeGenerator]:
    def build(snowflakes: Any) -> OutgoingRequest:
        return OutgoingRequest(
            envelope=envelope.make_request(
                request_id=snowflakes.next_unsafe(),
                address=address,
                tag=KeyRpc.tag,
                payload=KeyPayload(id=key),
            ),
            annotations=KeyRpc.annotations,
            context=Context.empty(),
            rpc=KeyRpc,
            last_received_reply=None,
            respond=lambda _reply: fx.void,
        )

    return SnowflakeGenerator().map(build)


def _messages(prefix: str) -> Generator[Any, Any, MessageStorageService]:
    return (yield from SqlMessageStorage.make(prefix=prefix))


def _runners(prefix: str) -> Generator[Any, Any, RunnerStorageService]:
    return (yield from SqlRunnerStorage.make(prefix=prefix))


def _addresses(messages: list[Any]) -> set[tuple[str, str, str]]:
    return {
        (
            str(m.envelope.address.shard_id),
            m.envelope.address.entity_type,
            m.envelope.address.entity_id,
        )
        for m in messages
    }


def _key(address: EntityAddress) -> tuple[str, str, str]:
    return (str(address.shard_id), address.entity_type, address.entity_id)


def _save_both(
    storage: MessageStorageService, one: EntityAddress, other: EntityAddress
) -> Generator[Any, Any, tuple[OutgoingRequest, OutgoingRequest]]:
    first = yield from _request(one)
    second = yield from _request(other)
    assert isinstance((yield from storage.save_request(first)), SaveSuccess)
    assert isinstance((yield from storage.save_request(second)), SaveSuccess)
    for request in (first, second):
        found = yield from storage.request_id_for_primary_key(
            address=request.envelope.address, tag=KeyRpc.tag, id="1"
        )
        assert found == request.envelope.request_id
    return first, second


@pytest.mark.parametrize("field", ["entity_id", "entity_type"])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_entities_differing_only_in_case_accents_or_trailing_spaces_stay_distinct(
    client: fx.Layer[Any, Any], variant: str, field: str
) -> None:
    first, second = VARIANTS[variant]
    one = _address(**{field: first})
    other = _address(**{field: second})
    shards = [one.shard_id]

    def body():
        storage = yield from _messages(_prefix())
        yield from _save_both(storage, one, other)
        messages = yield from storage.unprocessed_messages(shards)
        assert _addresses(messages) == {_key(one), _key(other)}

        yield from storage.clear_address(one)
        yield from storage.reset_shards(shards)
        messages = yield from storage.unprocessed_messages(shards)
        assert _addresses(messages) == {_key(other)}

        yield from storage.reset_address(one)
        assert (yield from storage.unprocessed_messages(shards)) == []

    _run(client, body)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_primary_keys_differing_only_in_case_accents_or_trailing_spaces_stay_distinct(
    client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = VARIANTS[variant]
    address = _address()

    def body():
        storage = yield from _messages(_prefix())
        one = yield from _request(address, first)
        other = yield from _request(address, second)
        assert isinstance((yield from storage.save_request(one)), SaveSuccess)
        assert isinstance((yield from storage.save_request(other)), SaveSuccess)
        for key, request in ((first, one), (second, other)):
            found = yield from storage.request_id_for_primary_key(
                address=address, tag=KeyRpc.tag, id=key
            )
            assert found == request.envelope.request_id
        assert len((yield from storage.unprocessed_messages([address.shard_id]))) == 2

    _run(client, body)


@pytest.mark.parametrize("variant", sorted(CASE_AND_ACCENTS))
def test_shard_groups_differing_only_in_case_or_accents_hold_their_own_messages(
    client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = CASE_AND_ACCENTS[variant]
    # a primary key leaves out the shard, so the entities differ too
    one = _address(group=first, entity_id="a")
    other = _address(group=second, entity_id="b")

    def body():
        storage = yield from _messages(_prefix())
        yield from _save_both(storage, one, other)
        assert _addresses((yield from storage.unprocessed_messages([one.shard_id]))) == {_key(one)}
        assert _addresses((yield from storage.unprocessed_messages([other.shard_id]))) == {
            _key(other)
        }
        yield from storage.reset_shards([one.shard_id])
        assert (yield from storage.unprocessed_messages([other.shard_id])) == []
        assert _addresses((yield from storage.unprocessed_messages([one.shard_id]))) == {_key(one)}

    _run(client, body)


@pytest.mark.parametrize("advisory", [True, False], ids=["advisory", "no advisory"])
@pytest.mark.parametrize("variant", sorted(CASE_AND_ACCENTS))
def test_shard_groups_differing_only_in_case_or_accents_lock_separately(
    client: fx.Layer[Any, Any], variant: str, advisory: bool
) -> None:
    first, second = CASE_AND_ACCENTS[variant]
    one = shard_id.make(first, 1)
    other = shard_id.make(second, 1)
    address_a = runner_address.make("runner-a", 1234)
    address_b = runner_address.make("runner-b", 1234)

    def body():
        prefix = _prefix()
        storage_a = yield from _runners(prefix)
        storage_b = yield from _runners(prefix)
        assert (yield from storage_a.acquire(address_a, [one])) == [one]
        assert (yield from storage_b.acquire(address_b, [other])) == [other]
        assert (yield from storage_a.refresh(address_a, [one])) == [one]
        assert (yield from storage_b.refresh(address_b, [other])) == [other]
        assert (yield from storage_b.acquire(address_b, [one])) == []

        yield from storage_a.release(address_a, one)
        assert (yield from storage_b.refresh(address_b, [other])) == [other]
        assert (yield from storage_a.acquire(address_a, [other])) == []

    _run(
        client,
        body,
        available_shard_groups=(first, second),
        assigned_shard_groups=(first, second),
        shards_per_group=2,
        shard_lock_disable_advisory=not advisory,
    )


@pytest.mark.parametrize("client", ["mysql"], indirect=True)
def test_shards_whose_lock_names_do_not_collide_keep_effects_lock_names(
    client: fx.Layer[Any, Any],
) -> None:
    """Runners of Effect and of pyfect sharing a cluster take one MySQL lock
    per shard; only the shards of ``Alpha`` and ``alpha`` are renamed."""
    shards = [shard_id.make(group, 1) for group in ("default", "Alpha", "alpha")]
    address = runner_address.make("runner-a", 1234)

    def body():
        prefix = _prefix()
        storage = yield from _runners(prefix)
        assert sorted((yield from storage.acquire(address, shards)), key=str) == sorted(
            shards, key=str
        )
        sql = yield from SqlClient()
        rows: Sequence[Any] = yield from sql(
            "SELECT IS_USED_LOCK({}) AS d, IS_USED_LOCK({}) AS a",
            f"{prefix}.default:1",
            f"{prefix}.Alpha:1",
        )
        assert rows[0]["d"] is not None
        assert rows[0]["a"] is None

    _run(client, body, available_shard_groups=("default", "Alpha", "alpha"), shards_per_group=1)


@pytest.mark.parametrize("variant", sorted(CASE_AND_ACCENTS))
def test_runner_addresses_differing_only_in_case_or_accents_stay_distinct(
    client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = CASE_AND_ACCENTS[variant]
    one = runner.make(address=runner_address.make(first, 1234), groups=("default",), weight=1)
    other = runner.make(address=runner_address.make(second, 1234), groups=("default",), weight=1)
    shard = shard_id.make("default", 1)

    def body():
        storage = yield from _runners(_prefix())
        first_id = yield from storage.register(one, True)
        other_id = yield from storage.register(other, True)
        assert first_id != other_id
        assert sorted(r.address.host for r, _ in (yield from storage.get_runners)) == sorted(
            [first, second]
        )
        yield from storage.set_runner_health(one.address, False)
        assert {r.address.host: h for r, h in (yield from storage.get_runners)} == {
            first: False,
            second: True,
        }

        assert (yield from storage.acquire(one.address, [shard])) == [shard]
        assert (yield from storage.acquire(other.address, [shard])) == []
        assert (yield from storage.refresh(other.address, [shard])) == []
        yield from storage.release_all(other.address)
        assert (yield from storage.refresh(one.address, [shard])) == [shard]

        yield from storage.unregister(one.address)
        assert [r.address.host for r, _ in (yield from storage.get_runners)] == [second]

    _run(client, body, shard_lock_disable_advisory=True)


def _first(loader: migrator.Loader, count: int) -> migrator.Loader:
    return loader.map(lambda loaded: [m for m in loaded if m[0] <= count])


def _key_statistics(prefix: str) -> Generator[Any, Any]:
    """Queries on the unindexed key columns, so SQL Server keeps statistics
    on them (which a column's change must not trip over)."""
    sql = yield from SqlClient()
    messages = sql.identifier(f"{prefix}_messages")
    yield from sql(
        "DELETE FROM {} WHERE entity_type = {} AND entity_id = {}", messages, "User", "nobody"
    )
    if sql.dialect != "mssql":
        return
    rows: Sequence[Any] = yield from sql(
        "SELECT COUNT(*) AS n FROM sys.stats s JOIN sys.stats_columns sc "
        "ON sc.object_id = s.object_id AND sc.stats_id = s.stats_id JOIN sys.columns c "
        "ON c.object_id = sc.object_id AND c.column_id = sc.column_id "
        "WHERE s.object_id = OBJECT_ID({}) AND s.auto_created = 1 "
        "AND c.name IN ('entity_type', 'entity_id')",
        f"{prefix}_messages",
    )
    assert int(str(rows[0]["n"])) > 0


def test_upgrades_tables_that_already_have_rows(client: fx.Layer[Any, Any]) -> None:
    """Tables made by Effect's migrations keep their rows, messages, runners
    and locks, after the storages' later migrations."""
    prefix = _prefix()
    old = _address(entity_id="alice")
    new = _address(entity_id="Alice")
    shard = shard_id.make("default", 1)
    owner = runner.make(address=runner_address.make("runner-a", 1), groups=("default",), weight=1)
    rival = runner_address.make("RUNNER-A", 1)

    def body():
        yield from migrator.make()(
            loader=_first(SqlMessageStorage.migrations(prefix=prefix), 3),
            table=f"{prefix}_migrations",
        )
        yield from migrator.make()(
            loader=_first(SqlRunnerStorage.migrations(prefix=prefix), 1),
            table=f"{prefix}_runner_migrations",
        )
        before = yield from SqlMessageStorage.make_encoded_storage(prefix=prefix)
        before_storage = yield from make_encoded(before)
        request = yield from _request(old)
        assert isinstance((yield from before_storage.save_request(request)), SaveSuccess)
        yield from before_storage.unprocessed_messages([shard])
        yield from before_storage.reset_shards([shard])
        yield from _key_statistics(prefix)
        before_runners = yield from SqlRunnerStorage.make_storage(prefix=prefix)
        machine_id = yield from before_runners.register(owner, True)
        assert (yield from before_runners.acquire(owner.address, [shard])) == [shard]

        storage = yield from _messages(prefix)
        assert _addresses((yield from storage.unprocessed_messages([shard]))) == {_key(old)}
        found = yield from storage.request_id_for_primary_key(address=old, tag=KeyRpc.tag, id="1")
        assert found == request.envelope.request_id
        newer = yield from _request(new)
        assert isinstance((yield from storage.save_request(newer)), SaveSuccess)
        yield from storage.reset_shards([shard])
        assert _addresses((yield from storage.unprocessed_messages([shard]))) == {
            _key(old),
            _key(new),
        }

        runners = yield from _runners(prefix)
        assert (yield from runners.register(owner, True)) == machine_id
        assert [r for r, _ in (yield from runners.get_runners)] == [owner]
        assert (yield from runners.refresh(owner.address, [shard])) == [shard]
        assert (yield from runners.acquire(rival, [shard])) == []

    _run(client, body, shard_lock_disable_advisory=True)
