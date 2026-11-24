"""Text becomes UTF-8 bytes through ``pyfect._js.text_encode`` (Effect's ``TextEncoder``).

``text.encode("utf-8", "surrogatepass")`` writes a lone surrogate as its own three bytes, where
``TextEncoder`` writes U+FFFD: a password hash or a percent-encoded URL part made that way never
matches Effect's (``tests/test_text_encoder_boundaries.py``). The sites below keep it on purpose;
any other is an error. A new one goes through ``text_encode``, or here with its reason.
"""

import ast
from pathlib import Path

import _source

_KEPT: dict[tuple[str, str], str] = {
    ("_text_keys.py", "key_bytes"): "distinct texts must give distinct keys",
    ("_whatwg_url/_percent.py", "decode"): "a lone surrogate stays, for a strict decode to refuse",
    ("net/dns/_records.py", "_quote"): "presentation-format byte escapes, no Effect counterpart",
    ("net/dns/_records.py", "_format_name"): "presentation-format byte escapes, as _quote",
    ("http/multipart.py", "persisted_file_name"): "a byte count: three bytes either way",
    ("persistence/persisted_queue/_sql_statements.py", "offer"): "a byte count, as above",
    ("sql/pg/error.py", "validate_channel_name"): "a byte count, as above",
}

_UTF8 = frozenset({"utf-8", "utf8", "UTF-8", "UTF8"})


def _is_surrogatepass_utf8(node: ast.AST) -> bool:
    """``x.encode(encoding, errors)`` with UTF-8 (the default) and ``"surrogatepass"``."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "encode"
    ):
        return False
    given = dict(zip(("encoding", "errors"), node.args, strict=False))
    given |= {k.arg: k.value for k in node.keywords if k.arg is not None}
    encoding, errors = given.get("encoding"), given.get("errors")
    return (
        isinstance(errors, ast.Constant)
        and errors.value == "surrogatepass"
        and (encoding is None or (isinstance(encoding, ast.Constant) and encoding.value in _UTF8))
    )


def _sites(path: Path) -> list[tuple[str, str]]:
    relative = path.relative_to(_source.SRC).as_posix()
    hits: list[tuple[str, str]] = []

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name
        if _is_surrogatepass_utf8(node):
            hits.append((relative, function))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(_source.tree(path), "<module>")
    return hits


def test_text_becomes_utf8_through_text_encode() -> None:
    sites = [
        site
        for path in _source.files(_source.SRC)
        if "surrogatepass" in _source.text(path)
        for site in _sites(path)
    ]
    assert [site for site in sites if site not in _KEPT] == []
    assert sorted(set(_KEPT) - set(sites)) == [], "a kept site is gone: drop it from _KEPT"


def test_the_guard_sees_surrogatepass_encodes() -> None:
    tree = _source.parse(
        't.encode("utf-8", "surrogatepass")\n'
        't.encode(errors="surrogatepass")\n'
        't.encode(encoding="utf8", errors="surrogatepass")\n'
        't.encode("utf-16-le", "surrogatepass")\n'
        't.encode("utf-8")\n'
    )
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert [_is_surrogatepass_utf8(call) for call in calls] == [True, True, True, False, False]
