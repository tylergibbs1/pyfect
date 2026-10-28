"""The statement compiler beyond Effect's ``Statement.test.ts``: empty
``IN`` lists, ``update`` omissions and the cache of nested fragments."""

import pyfect as fx
from pyfect.sql import statement as st


def _nothing(*_args: object) -> st.Compiled:
    return ("", ())


def _pg() -> st.Compiler:
    return st.make_compiler(
        dialect="pg",
        placeholder=lambda index, _value: f"${index}",
        on_identifier=lambda name, _without_transform: st.default_escape('"')(name),
        on_record_update=_nothing,
        on_custom=_nothing,
    )


def _constructor(compiler: st.Compiler) -> st.Constructor:
    return st.make(fx.never, compiler, [], None)


def test_an_empty_in_list_matches_nothing():
    sql = _constructor(st.make_compiler_sqlite())
    assert sql("SELECT * FROM t WHERE a IN {}", sql.in_([])).compile() == (
        "SELECT * FROM t WHERE a IN (SELECT NULL WHERE 1=0)",
        (),
    )


def test_an_empty_in_list_after_in_inside_a_line_comment_stays_empty_parens():
    sql = _constructor(st.make_compiler_sqlite())
    compiled = sql("SELECT * FROM t -- filter a IN\nWHERE b = {} AND c IN {}", 1, sql.in_([]))
    assert compiled.compile()[0].endswith("c IN (SELECT NULL WHERE 1=0)")
    commented = sql("SELECT {} -- a IN {}", 1, sql.in_([]))
    assert commented.compile() == ("SELECT ? -- a IN ()", (1,))


def test_an_empty_not_in_list_on_postgres_compares_with_an_empty_array():
    sql = _constructor(_pg())
    assert sql("SELECT * FROM t WHERE a NOT IN {}", sql.in_([])).compile() == (
        "SELECT * FROM t WHERE a <> ALL('{}')",
        (),
    )


def test_update_leaves_out_the_omitted_columns():
    sql = _constructor(st.make_compiler_sqlite())
    statement = sql("UPDATE people SET {}", sql.update({"id": 1, "name": "Ada"}, omit=["id"]))
    assert statement.compile() == ('UPDATE people SET "name" = ?', ("Ada",))


def test_compiling_a_fragment_nested_with_other_numbering_keeps_its_own_cached():
    """The nested compile renumbers the fragment; that result is not the
    fragment's own, so it must not be cached for it."""
    sql = _constructor(_pg())
    returning = sql("{} AS label", "label")
    nested = sql(
        "INSERT INTO people {}, {} AS extra",
        sql.insert({"name": "Ada"}).returning(returning),
        "extra",
    )

    assert nested.compile()[0].endswith("RETURNING $2 AS label, $3 AS extra")
    assert returning.compile() == ("$1 AS label", ("label",))
