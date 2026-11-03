"""Every URL pyfect gives back is a ``Url``, whose ``str()`` is the URL.

``urllib.parse.SplitResult``'s ``str()`` is its repr, so
``f"{config_url}/payouts"`` sent a request to ``SplitResult(scheme=...)/payouts``
(DOGFOOD outlay 6). A ``Url`` is still a ``SplitResult``; JavaScript's ``URL``
writes its ``href`` the same way."""

from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import SplitResult

import pyfect as fx
from pyfect import config
from pyfect import config_provider as cp
from pyfect import schema as S
from pyfect.http import request as http_request
from pyfect.http import url as http_url
from pyfect.net import net_address

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"


def _ok[A](result: fx.Result[A, object]) -> A:
    assert isinstance(result, fx.Ok), result
    return result.value


def test_a_config_url_writes_itself_out_in_an_f_string():
    provider = cp.from_unknown({"PAYOUT_URL": "http://localhost:8000"})
    url = fx.run_sync(config.url("PAYOUT_URL").parse(provider).or_die())
    assert f"{url}/payouts" == "http://localhost:8000/payouts"
    assert url.geturl() == "http://localhost:8000"  # still a SplitResult


def test_every_url_producer_gives_a_url_whose_str_is_the_href():
    request = http_request.get("https://example.com/a")
    produced: list[SplitResult | None] = [
        _ok(http_url.from_string("HTTPS://Example.com:443/a/../b c")),
        http_url.set_search(_ok(http_url.from_string("https://example.com/b")), "q=1"),
        _ok(S.decode_unknown_result(S.URLFromString)("https://example.com/b%20c")),
        _ok(net_address.to_url(_ok(net_address.ip_from_string("127.0.0.1")), "https")),
        request.to_url(),
    ]
    for url in produced:
        assert isinstance(url, http_url.Url), repr(url)
        assert str(url) == http_url.href(url)
        assert "(" not in str(url)


def test_a_setter_given_a_plain_split_result_gives_a_url():
    plain = SplitResult("https", "example.com", "/", "", "")
    assert str(http_url.set_hash(plain, "top")) == "https://example.com/#top"


# urllib.parse's result types write their repr as their str().
_REPR_AS_STR = frozenset(
    {"SplitResult", "ParseResult", "DefragResult", "SplitResultBytes", "ParseResultBytes"}
)


def _repr_as_str_names(tree: ast.Module) -> set[str]:
    """The names a module binds to ``urllib.parse``'s result types, and the
    dotted names it can reach them by (``urllib.parse.SplitResult``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "urllib.parse":
            names |= {a.asname or a.name for a in node.names if a.name in _REPR_AS_STR}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("urllib", "urllib.parse"):
                    module = alias.asname or "urllib.parse"
                    names |= {f"{module}.{name}" for name in _REPR_AS_STR}
    return names


def _given_back(annotation: ast.expr) -> set[str]:
    """The names in a return or field annotation, but those inside a
    ``Callable[...]`` (a callback's parameters are inputs)."""
    if isinstance(annotation, ast.Subscript) and ast.unparse(annotation.value).endswith("Callable"):
        return set()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return _given_back(ast.parse(annotation.value, mode="eval").body)
    if isinstance(annotation, ast.Name | ast.Attribute):
        return {ast.unparse(annotation)}
    found = set[str]()
    for child in ast.iter_child_nodes(annotation):
        if isinstance(child, ast.expr):
            found |= _given_back(child)
    return found


def test_no_api_gives_back_a_value_whose_str_is_its_repr():
    """Return types and fields (and module constants) are ``Url``, not a
    ``urllib.parse`` result; parameters (and input type aliases) may take one."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), str(path))
        banned = _repr_as_str_names(tree)
        if not banned:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns:
                annotation = node.returns
            elif isinstance(node, ast.AnnAssign):
                annotation = node.annotation
            else:
                continue
            if _given_back(annotation) & banned:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == [], "give back pyfect._url.Url (as_url(...) converts)"


def test_the_guard_sees_a_split_result_given_back():
    tree = ast.parse(
        "from urllib.parse import SplitResult as S\n"
        "def f() -> S | None: ...\n"
        "x: Callable[[S], None]\n"
    )
    banned = _repr_as_str_names(tree)
    func, field = tree.body[1], tree.body[2]
    assert isinstance(func, ast.FunctionDef) and isinstance(field, ast.AnnAssign)
    assert func.returns is not None and _given_back(func.returns) & banned == {"S"}
    assert _given_back(field.annotation) & banned == set()


def test_the_guard_sees_a_dotted_or_quoted_split_result():
    tree = ast.parse(
        "import urllib.parse\n"
        "def f() -> urllib.parse.SplitResult: ...\n"
        "def g() -> 'list[urllib.parse.ParseResult]': ...\n"
    )
    banned = _repr_as_str_names(tree)
    found = [
        _given_back(node.returns) & banned
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.returns is not None
    ]
    assert found == [{"urllib.parse.SplitResult"}, {"urllib.parse.ParseResult"}]
