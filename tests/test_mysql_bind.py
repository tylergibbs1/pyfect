"""How the text protocol finds its ``?`` placeholders, following MySQL's lexer.

A placeholder missed or invented here moves every later parameter, or puts a
parameter's literal inside a string the server reads differently.
"""

import pytest

pytest.importorskip("asyncmy")

from pyfect.sql.mysql._bind import PlaceholderMismatch, bind


def _literal(value: object) -> str:
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
