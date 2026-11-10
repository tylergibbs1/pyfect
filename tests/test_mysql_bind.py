"""How the text protocol finds its ``?`` placeholders, following MySQL's lexer.

A placeholder missed or invented here moves every later parameter, or puts a
parameter's literal inside a string the server reads differently.
"""

import pytest

pytest.importorskip("asyncmy")

from pyfect.sql.mysql._bind import PlaceholderMismatch, bind


def _literal(value: object, _assigns: bool) -> str:
    return f"<{value}>"


def _bind(sql: str, *params: object, no_backslash_escapes: bool = False) -> str:
    return bind(sql, params, _literal, no_backslash_escapes=no_backslash_escapes)


@pytest.mark.parametrize(
    ("sql", "bound"),
    [
        # A backslash at the end of a string only quotes the quote by default.
        (r"SELECT 'a\' ?' , ?", r"SELECT 'a\' ?' , <1>"),
        (r'SELECT "a\" ?" , ?', r'SELECT "a\" ?" , <1>'),
        ("SELECT 'it''s ?', ?", "SELECT 'it''s ?', <1>"),
    ],
)
def test_a_backslash_escapes_a_quote_by_default(sql: str, bound: str):
    assert _bind(sql, 1) == bound


@pytest.mark.parametrize(
    ("sql", "bound"),
    [
        (r"SELECT 'a\', ?", r"SELECT 'a\', <1>"),
        (r'SELECT "a\", ?', r'SELECT "a\", <1>'),
        (r"SELECT 'a\\', ?", r"SELECT 'a\\', <1>"),
        ("SELECT 'it''s ?', ?", "SELECT 'it''s ?', <1>"),
    ],
)
def test_a_backslash_is_plain_text_under_no_backslash_escapes(sql: str, bound: str):
    assert _bind(sql, 1, no_backslash_escapes=True) == bound


@pytest.mark.parametrize(
    ("sql", "bound"),
    [
        ("SELECT 1 -- ?\n, ?", "SELECT 1 -- ?\n, <1>"),
        ("SELECT 1 --\t?\n, ?", "SELECT 1 --\t?\n, <1>"),
        ("SELECT 1 --\n, ?", "SELECT 1 --\n, <1>"),
        ("SELECT 1 --\r?\n, ?", "SELECT 1 --\r?\n, <1>"),
        ("SELECT 1 --\x01?\n, ?", "SELECT 1 --\x01?\n, <1>"),
        ("SELECT ? --", "SELECT <1> --"),
        ("SELECT 1 # ?\n, ?", "SELECT 1 # ?\n, <1>"),
    ],
)
def test_a_double_dash_before_whitespace_or_a_control_character_is_a_comment(sql: str, bound: str):
    assert _bind(sql, 1) == bound


def test_a_double_dash_before_anything_else_is_two_minus_signs():
    assert _bind("SELECT 5--?", 1) == "SELECT 5--<1>"


def test_a_quote_in_a_double_dash_comment_opens_no_string():
    """``--`` before a newline is a comment on an empty line, so a quote on
    the next line opens a string."""
    assert _bind("SELECT --\n'?', ?", 1) == "SELECT --\n'?', <1>"
    assert _bind("SELECT -- '\n?", 1) == "SELECT -- '\n<1>"


@pytest.mark.parametrize(
    ("sql", "bound"),
    [
        ("SELECT /*!50000 ? */ 1", "SELECT /*!50000 <1> */ 1"),
        ("SELECT /*M! ? */ 1", "SELECT /*M! <1> */ 1"),
        ("SELECT /*!50000 '?' */ ?", "SELECT /*!50000 '?' */ <1>"),
        ("SELECT /* ? */ /*+ ? */ ?", "SELECT /* ? */ /*+ ? */ <1>"),
    ],
)
def test_the_server_runs_what_is_inside_a_version_comment(sql: str, bound: str):
    """MySQL and MariaDB read ``/*! ... */`` and ``/*M! ... */`` as statement text."""
    assert _bind(sql, 1) == bound


def test_counts_placeholders_with_the_mode_in_force():
    with pytest.raises(PlaceholderMismatch):
        _bind(r"SELECT 'a\', ?", 1)


def _assigns(sql: str, *params: object) -> str:
    def literal(value: object, assigns: bool) -> str:
        return "<pairs>" if assigns else "<value>"

    return bind(sql, params, literal, no_backslash_escapes=False)


@pytest.mark.parametrize(
    ("sql", "bound"),
    [
        # mysql2's sql-escaper expands an object only where an assignment can start.
        ("UPDATE t SET ? WHERE id = ?", "UPDATE t SET <pairs> WHERE id = <value>"),
        ("UPDATE t SET a = 1, ?", "UPDATE t SET a = 1, <pairs>"),
        ("INSERT INTO t SET ?", "INSERT INTO t SET <pairs>"),
        (
            "INSERT INTO t (a) VALUES (1) ON DUPLICATE KEY UPDATE ?",
            "INSERT INTO t (a) VALUES (1) ON DUPLICATE KEY UPDATE <pairs>",
        ),
        ("SELECT ?", "SELECT <value>"),
        ("UPDATE t SET a = ?", "UPDATE t SET a = <value>"),
        ("UPDATE t SET a = 1 WHERE ?", "UPDATE t SET a = 1 WHERE <value>"),
        ("SELECT 1 FROM t WHERE (SET), ?", "SELECT 1 FROM t WHERE (SET), <value>"),
        ("UPDATE t SET a = 1 LIMIT 1, ?", "UPDATE t SET a = 1 LIMIT 1, <value>"),
        ("UPDATE t SET a = (1, ?)", "UPDATE t SET a = (1, <value>)"),
        ("UPDATE t SET a = 1; SELECT ?", "UPDATE t SET a = 1; SELECT <value>"),
        ("SELECT 'SET' ?", "SELECT 'SET' <value>"),
        ("SELECT `set`, ?", "SELECT `set`, <value>"),
    ],
)
def test_a_dict_is_assignments_only_where_mysql2_expands_it(sql: str, bound: str):
    assert _assigns(sql, *({"a": 1} for _ in range(sql.count("?")))) == bound


def test_only_dicts_ask_for_assignments():
    assert _assigns("UPDATE t SET ?", [1]) == "UPDATE t SET <value>"
