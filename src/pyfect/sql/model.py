"""Repositories of models (Effect's ``effect/sql/SqlModel``): insert,
update, find and delete a ``Model.Class``'s rows::

    repo = yield from sql_model.make_repository(
        User, table_name="users", span_prefix="UserRepository", id_column="id"
    )
    user = yield from repo.insert(User.insert.make({"name": "Ada"}))  # a User

``insert`` and ``update`` take the model's ``insert`` / ``update`` variant
(the TypedDicts given to ``Model.Class``) and return the row as the model.
``find_by_id`` and ``delete`` take the id, encoded with the id field's
schema (pyright cannot read an attribute's type from a column name, so it
is checked there). With ``soft_delete_column``, ``delete`` sets that
column to ``CURRENT_TIMESTAMP`` and the reads skip rows where it is set.
``make_resolvers`` gives the same operations as batched resolvers.

``insert`` returns the row through the compiler's ``returning`` (``RETURNING
*``, ``OUTPUT INSERTED.*`` on SQL Server); ``update`` appends ``returning *``,
as Effect does, so on SQL Server and ClickHouse only ``update_void`` works.
On MySQL both run the statement followed by a ``SELECT`` of the row.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Never, Protocol, TypeVar, cast

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.effect import catch_tag, die
from pyfect.errors import NoSuchElementException
from pyfect.schema import Codec, SchemaError
from pyfect.schema.model import ModelVariants
from pyfect.sql import resolver as sql_resolver
from pyfect.sql import schema as sql_schema
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import ResultLengthMismatch, SqlError
from pyfect.sql.resolver import SqlResolver
from pyfect.sql.statement import Fragment, Identifier, Statement

A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
U_co = TypeVar("U_co", covariant=True)


class ModelType(Protocol[A_co, I_co, U_co]):
    """A ``Model.Class``: its rows are ``A``, its insert variant ``I`` and
    its update variant ``U``."""

    def __model_variants__(self) -> ModelVariants[A_co, I_co, U_co]: ...


In_contra = TypeVar("In_contra", contravariant=True)
Up_contra = TypeVar("Up_contra", contravariant=True)


@dataclass(frozen=True, slots=True)
class Repository(Generic[A_co, In_contra, Up_contra]):
    """A model's table operations (Effect's ``makeRepository`` result)."""

    insert: Callable[[In_contra], Effect[A_co, SchemaError | SqlError]]
    insert_void: Callable[[In_contra], Effect[None, SchemaError | SqlError]]
    update: Callable[[Up_contra], Effect[A_co, SchemaError | SqlError]]
    update_void: Callable[[Up_contra], Effect[None, SchemaError | SqlError]]
    find_by_id: Callable[[object], Effect[A_co, NoSuchElementException | SchemaError | SqlError]]
    delete: Callable[[object], Effect[None, SchemaError | SqlError]]


A_contra = TypeVar("A_contra", contravariant=True)


@dataclass(frozen=True, slots=True)
class Resolvers(Generic[A_contra, In_contra]):
    """A model's table operations as batched resolvers (Effect's
    ``makeResolvers`` result); run one with ``sql.resolver.request``."""

    insert: SqlResolver[In_contra, A_contra, ResultLengthMismatch | SchemaError | SqlError, Any]
    insert_void: SqlResolver[In_contra, None, SchemaError | SqlError, Any]
    find_by_id: SqlResolver[
        Hashable, A_contra, NoSuchElementException | SchemaError | SqlError, Any
    ]
    delete: SqlResolver[Hashable, None, SchemaError | SqlError, Any]


@dataclass(frozen=True, slots=True)
class _Table:
    """A model's table, as the operations write it."""

    sql: SqlClientService
    model: Any
    table: str
    id_column: str
    soft_delete_column: str | None

    @property
    def name(self) -> Identifier:
        return self.sql.identifier(self.table)

    @property
    def id(self) -> Identifier:
        return self.sql.identifier(self.id_column)

    def live(self, where: Fragment) -> Fragment:
        """``where``, and the row not soft-deleted."""
        if self.soft_delete_column is None:
            return where
        deleted = self.sql("{} is null", self.sql.identifier(self.soft_delete_column))
        return self.sql.and_([where, deleted])

    def id_schema(self) -> Codec[Any, Any, Any, Any]:
        return self.model.fields()[self.id_column]


@dataclass(frozen=True, slots=True)
class _Columns:
    """A model's table and columns, checked against its variants when
    ``make_repository`` / ``make_resolvers`` is called."""

    model: Any
    table: str
    id_column: str
    soft_delete_column: str | None

    def on(self, sql: SqlClientService) -> _Table:
        return _Table(sql, self.model, self.table, self.id_column, self.soft_delete_column)


def _columns(
    variants: ModelVariants[Any, Any, Any],
    table_name: str,
    id_column: str,
    soft_delete_column: str | None,
) -> _Columns:
    """Effect checks ``id_column`` against the update variant's keys at
    compile time; pyright has no ``keyof`` for a TypedDict, so it is checked
    here, before any effect runs."""
    model: Any = variants.model
    selected = model.fields()
    update = variants.update.fields
    if id_column not in selected or id_column not in update:
        hint = (
            " (a GeneratedByDb field is in select and json only: declare the id with"
            " Model.field_only(['select', 'update', 'json'])(...))"
            if id_column in selected
            else ""
        )
        raise ValueError(
            f"{model.__name__}: id_column {id_column!r} must be a field of the select and"
            f" update variants; the 'update' variant has: {', '.join(map(repr, update))}{hint}"
        )
    if soft_delete_column is not None and soft_delete_column not in selected:
        raise ValueError(f"{model.__name__} has no {soft_delete_column!r} field")
    return _Columns(model, table_name, id_column, soft_delete_column)


def make_repository[A, In, Up](
    model: ModelType[A, In, Up],
    *,
    table_name: str,
    span_prefix: str,
    id_column: str,
    soft_delete_column: str | None = None,
) -> Effect[Repository[A, In, Up], Never, SqlClient]:
    """A repository of ``model`` on ``table_name`` (Effect's
    ``makeRepository``); spans are named ``<span_prefix>.insert`` and so on.
    ``id_column`` must be a field of the ``select`` and ``update`` variants
    (``ValueError`` when called)."""
    variants = model.__model_variants__()
    columns = _columns(variants, table_name, id_column, soft_delete_column)

    def build(sql: SqlClientService) -> Repository[A, In, Up]:
        return _repository(columns.on(sql), variants, span_prefix)

    return SqlClient().map(build)


def _then_select(t: _Table, statement: Fragment, select_where: Fragment) -> Effect[Any, SqlError]:
    """MySQL's stand-in for ``RETURNING``: the statement, then a ``SELECT``
    of the row."""
    sql = t.sql
    both = sql("{};\nselect * from {} where {};", statement, t.name, t.live(select_where))
    return both.unprepared.map(lambda results: results[1])


def _repository[A, In, Up](
    t: _Table, variants: ModelVariants[A, In, Up], prefix: str
) -> Repository[A, In, Up]:
    sql = t.sql
    model = variants.model

    def insert_statement(row: Mapping[str, object]) -> Statement[Any]:
        return sql("insert into {} {}", t.name, sql.insert(row))

    def update_statement(row: Mapping[str, object]) -> Statement[Any]:
        where = t.live(sql("{} = {}", t.id, row[t.id_column]))
        return sql("update {} set {} where {}", t.name, sql.update(row, [t.id_column]), where)

    def by_id(id: object) -> Fragment:
        return t.live(sql("{} = {}", t.id, id))

    def insert_returning(row: Mapping[str, object]) -> Effect[Any, SqlError]:
        return sql.on_dialect_or_else(
            mysql=lambda: _then_select(
                t, insert_statement(row), sql("{} = LAST_INSERT_ID()", t.id)
            ),
            or_else=lambda: sql("insert into {} {}", t.name, sql.insert(row).returning("*")),
        )

    def update_returning(row: Mapping[str, object]) -> Effect[Any, SqlError]:
        # Effect writes ``returning *`` itself here, not through the compiler,
        # so an update with its row fails on SQL Server and ClickHouse there too.
        return sql.on_dialect_or_else(
            mysql=lambda: _then_select(
                t, update_statement(row), sql("{} = {}", t.id, row[t.id_column])
            ),
            or_else=lambda: sql("{} returning *", update_statement(row)),
        )

    insert_one = sql_schema.find_one(
        request=variants.insert, result=model, execute=insert_returning
    )
    insert_void = sql_schema.void(request=variants.insert, execute=insert_statement)
    update_one = sql_schema.find_one(
        request=variants.update,
        result=model,
        execute=update_returning,
    )
    update_void = sql_schema.void(request=variants.update, execute=update_statement)
    find_one = sql_schema.find_one(
        request=t.id_schema(),
        result=model,
        execute=lambda id: sql("select * from {} where {}", t.name, by_id(id)),
    )

    def delete_statement(id: object) -> Statement[Any]:
        if t.soft_delete_column is None:
            return sql("delete from {} where {} = {}", t.name, t.id, id)
        column = sql.identifier(t.soft_delete_column)
        return sql("update {} set {} = CURRENT_TIMESTAMP where {}", t.name, column, by_id(id))

    delete_one = sql_schema.void(request=t.id_schema(), execute=delete_statement)

    def span(name: str, **attributes: object) -> Callable[[Effect[Any, Any]], Effect[Any, Any]]:
        def traced(effect: Effect[Any, Any]) -> Effect[Any, Any]:
            return effect.with_span(
                f"{prefix}.{name}", attributes=attributes, capture_stack_trace=False
            )

        return traced

    def id_of(row: object) -> object:
        return cast("Mapping[str, object]", row)[t.id_column]

    return Repository(
        insert=lambda value: span("insert")(_die_on_missing(insert_one(value))),
        insert_void=lambda value: span("insertVoid")(insert_void(value)),
        update=lambda value: span("update", id=id_of(value))(_die_on_missing(update_one(value))),
        update_void=lambda value: span("updateVoid", id=id_of(value))(update_void(value)),
        find_by_id=lambda id: span("findById", id=id)(find_one(id)),
        delete=lambda id: span("delete", id=id)(delete_one(id)),
    )


def _die_on_missing[A, E](effect: Effect[A, E | NoSuchElementException]) -> Effect[A, E]:
    """No row back from an insert or update is a defect, as in Effect."""
    return effect.pipe(catch_tag(NoSuchElementException, die))


def make_resolvers[A, In, Up](
    model: ModelType[A, In, Up],
    *,
    table_name: str,
    span_prefix: str,
    id_column: str,
    soft_delete_column: str | None = None,
) -> Effect[Resolvers[A, In], Never, SqlClient]:
    """``make_repository``'s insert, insert-without-result, find and delete
    as batched resolvers (Effect's ``makeResolvers``): the requests of one
    scheduler tick (within one transaction) run as one statement."""
    variants = model.__model_variants__()
    columns = _columns(variants, table_name, id_column, soft_delete_column)

    def build(sql: SqlClientService) -> Resolvers[A, In]:
        return _resolvers(columns.on(sql), variants, span_prefix)

    return SqlClient().map(build)


def _resolvers[A, In](
    t: _Table, variants: ModelVariants[A, In, Any], prefix: str
) -> Resolvers[A, In]:
    sql = t.sql

    def insert_rows(rows: Sequence[Mapping[str, object]]) -> Effect[Sequence[object], SqlError]:
        def mysql() -> Effect[Sequence[object], SqlError]:
            def one(row: Mapping[str, object]) -> Effect[object, SqlError]:
                statement = sql("insert into {} {}", t.name, sql.insert(row))
                where = sql("{} = LAST_INSERT_ID()", t.id)
                return _then_select(t, statement, where).map(lambda rows: rows[0])

            return for_each(rows, one, concurrency=10)

        return sql.on_dialect_or_else(
            mysql=mysql,
            or_else=lambda: sql("insert into {} {}", t.name, sql.insert(rows).returning("*")),
        )

    def where_ids(ids: Sequence[object]) -> Fragment:
        return t.live(sql.in_(t.id_column, ids))

    def delete_rows(ids: Sequence[object]) -> Effect[object, SqlError]:
        if t.soft_delete_column is None:
            return sql("delete from {} where {}", t.name, sql.in_(t.id_column, ids))
        column = sql.identifier(t.soft_delete_column)
        return sql("update {} set {} = CURRENT_TIMESTAMP where {}", t.name, column, where_ids(ids))

    id_column = t.id_column

    def result_id(result: Any, _row: object) -> Hashable:
        return getattr(result, id_column)

    insert = sql_resolver.ordered(
        request=variants.insert, result=variants.model, execute=insert_rows
    )
    insert_void = sql_resolver.void(
        request=variants.insert,
        execute=lambda rows: sql("insert into {} {}", t.name, sql.insert(rows)),
    )
    find_by_id = sql_resolver.find_by_id(
        id=t.id_schema(),
        result=variants.model,
        result_id=result_id,
        execute=lambda ids: sql("select * from {} where {}", t.name, where_ids(ids)),
    )
    delete = sql_resolver.void(request=t.id_schema(), execute=delete_rows)
    return Resolvers(
        insert=insert.with_span(f"{prefix}.insertResolver"),
        insert_void=insert_void.with_span(f"{prefix}.insertVoidResolver"),
        find_by_id=find_by_id.with_span(f"{prefix}.findByIdResolver"),
        delete=delete.with_span(f"{prefix}.deleteResolver"),
    )


__all__ = ["ModelType", "Repository", "Resolvers", "make_repository", "make_resolvers"]
