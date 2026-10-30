"""Ports of Effect's ``sql-sqlite-node/test/SqlModelServices.test.ts``
(``SqlModel`` insert with schemas needing services, on SQLite).

Each test's docstring is the Effect test title. ``Context.Service`` is a
``Tag``; ``Model.Class<User>("User")({...})`` is ``class User(Model.Class)``.

Adapted: "decoder is supplied at request execution, not resolver
construction" does not assert Node's ``process.versions``; "a real
returned-row schema failure keeps its typed SchemaError" stores ``6`` as
``"6"`` (Python's ``sqlite3`` binds an ``int``; Node binds the double
``6.0``).
"""

from dataclasses import dataclass

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.context import Tag
from pyfect.schema import getter as G
from pyfect.schema import model as Model
from pyfect.schema import transformation as T
from pyfect.schema.issue import Issue
from pyfect.sql import SqlClient, SqlError
from pyfect.sql import model as sql_model
from pyfect.sql import resolver as R

from ._sqlite import make_memory_client


@dataclass(frozen=True)
class _Prefix:
    prefix: str


class NameDecoder(Tag[_Prefix], key="test/NameDecoder"):
    pass


class NameEncoder(Tag[_Prefix], key="test/NameEncoder"):
    pass


def _decode(value: str, _options: object) -> fx.Effect[str, Issue, NameDecoder]:
    return NameDecoder().map(lambda service: service.prefix + value)


def _encode(value: str, _options: object) -> fx.Effect[str, Issue, NameEncoder]:
    return NameEncoder().map(lambda service: service.prefix + value)


decoded_name = S.String.pipe(
    S.decode_to(S.String, T.Transformation(G.transform_effect(_decode), G.passthrough()))
)
encoded_name = S.String.pipe(
    S.decode_to(S.String, T.Transformation(G.passthrough(), G.transform_effect(_encode)))
)


class User(Model.Class):
    id: int
    name: str = Model.field(decoded_name)


class Both(Model.Class):
    id: int
    name: str = Model.field(
        Model.Field(select=decoded_name, insert=encoded_name, update=encoded_name)
    )


class Plain(Model.Class):
    id: int
    name: str


_OPTIONS = {"table_name": "users", "id_column": "id", "span_prefix": "User"}


def _create_table():
    sql = yield from make_memory_client()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    return sql


@testing.effect
def test_decoder_is_supplied_at_request_execution_not_resolver_construction():
    """SqlModel insert native node:sqlite runtime controls / decoder is supplied at request execution, not resolver construction"""  # noqa: E501
    sql = yield from fx.gen(_create_table)
    resolvers = yield from sql_model.make_resolvers(User, **_OPTIONS).pipe(
        fx.provide_service(SqlClient, sql)
    )
    result = yield from R.request({"id": 1, "name": "Ada"}, resolvers.insert).pipe(
        fx.provide_service(NameDecoder, _Prefix("read:"))
    )
    assert isinstance(result, User)
    assert result.name == "read:Ada"
    assert (yield from sql("SELECT * FROM users")) == [{"id": 1, "name": "Ada"}]
    found = yield from R.request(1, resolvers.find_by_id).pipe(
        fx.provide_service(NameDecoder, _Prefix("find:"))
    )
    assert found.name == "find:Ada"


@testing.effect
def test_distinct_encoder_and_decoder_execute_in_their_own_directions():
    """SqlModel insert native node:sqlite runtime controls / distinct encoder and decoder execute in their own directions"""  # noqa: E501
    sql = yield from fx.gen(_create_table)
    resolvers = yield from sql_model.make_resolvers(Both, **_OPTIONS).pipe(
        fx.provide_service(SqlClient, sql)
    )
    result = yield from (
        R.request({"id": 2, "name": "Ada"}, resolvers.insert)
        .pipe(fx.provide_service(NameEncoder, _Prefix("write:")))
        .pipe(fx.provide_service(NameDecoder, _Prefix("read:")))
    )
    assert isinstance(result, Both)
    assert result.name == "read:write:Ada"
    assert (yield from sql("SELECT * FROM users")) == [{"id": 2, "name": "write:Ada"}]


@testing.effect
def test_plain_model_insert_is_unchanged():
    """SqlModel insert native node:sqlite runtime controls / plain model insert is unchanged"""
    sql = yield from fx.gen(_create_table)
    resolvers = yield from sql_model.make_resolvers(Plain, **_OPTIONS).pipe(
        fx.provide_service(SqlClient, sql)
    )
    result = yield from R.request({"id": 3, "name": "plain"}, resolvers.insert)
    assert isinstance(result, Plain)
    assert result.name == "plain"
    assert (yield from sql("SELECT * FROM users")) == [{"id": 3, "name": "plain"}]


@testing.effect
def test_insert_void_does_not_execute_the_model_decoder():
    """SqlModel insert native node:sqlite runtime controls / insertVoid does not execute the model decoder"""  # noqa: E501
    sql = yield from fx.gen(_create_table)
    resolvers = yield from sql_model.make_resolvers(User, **_OPTIONS).pipe(
        fx.provide_service(SqlClient, sql)
    )
    yield from R.request({"id": 4, "name": "void"}, resolvers.insert_void)
    assert (yield from sql("SELECT * FROM users")) == [{"id": 4, "name": "void"}]


@testing.effect
def test_sql_failures_keep_their_typed_sql_error():
    """SqlModel insert native node:sqlite runtime controls / SQL failures keep their typed SqlError"""  # noqa: E501
    sql = yield from fx.gen(_create_table)
    yield from sql("INSERT INTO users VALUES (5, 'existing')")
    resolvers = yield from sql_model.make_resolvers(User, **_OPTIONS).pipe(
        fx.provide_service(SqlClient, sql)
    )
    error = yield from (
        R.request({"id": 5, "name": "duplicate"}, resolvers.insert)
        .pipe(fx.provide_service(NameDecoder, _Prefix("read:")))
        .flip()
    )
    assert isinstance(error, SqlError)
    assert (yield from sql("SELECT * FROM users")) == [{"id": 5, "name": "existing"}]


@testing.effect
def test_a_real_returned_row_schema_failure_keeps_its_typed_schema_error():
    """SqlModel insert native node:sqlite runtime controls / a real returned-row schema failure keeps its typed SchemaError"""  # noqa: E501
    sql = yield from make_memory_client()
    yield from sql("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    resolvers = yield from sql_model.make_resolvers(User, **_OPTIONS).pipe(
        fx.provide_service(SqlClient, sql)
    )
    error = yield from (
        R.request({"id": 6, "name": "invalid row"}, resolvers.insert)
        .pipe(fx.provide_service(NameDecoder, _Prefix("read:")))
        .flip()
    )
    assert isinstance(error, S.SchemaError)
    assert (yield from sql("SELECT * FROM users")) == [{"id": "6", "name": "invalid row"}]
