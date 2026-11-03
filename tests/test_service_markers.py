"""Every class a public signature requires is a tag or a ``ServiceMarker``
(an RPC group's handlers, a toolkit's, a middleware's client side), so
``router.serve`` and ``router.to_http_effect`` pass it through like a tag,
as Effect's ``Exclude<R, HttpRouter>`` does (DOGFOOD trawl 7). The router's
own markers (``Requires``, ``Raises``, ...) are unwrapped by ``serve`` and
must not be service markers, or they would leak into the server layer's
requirements.

Requirements are found structurally: every class named in the requirement
position of a return type ``Effect[A, E, R]``, ``Layer[ROut, E, RIn]``,
``Stream[A, E, R]``, ``Sink[..., R]`` or ``Channel[..., Env]`` anywhere in
``src/pyfect`` (through unions, type aliases, string annotations and
``import ... as`` names; type parameters and TypeVars are not classes).
"""

import ast
import collections
import functools
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"
ROUTER_MARKERS = SRC / "http" / "router" / "_markers.py"

# Where the requirement sits among each type's parameters.
R_INDEX = {"Effect": 2, "Layer": 2, "Stream": 2, "Sink": 4, "Channel": 6}
NOT_SERVICES = {"Any", "Never", "object"}
TAG_ROOTS = {"Tag", "Reference"}


def _head(expr: ast.expr) -> str:
    while isinstance(expr, ast.Subscript):
        expr = expr.value
    return ast.unparse(expr).split(".")[-1]


class _Index:
    """Every class, type alias and TypeVar defined under ``src/pyfect``, by
    name."""

    def __init__(self) -> None:
        self.trees = {path: ast.parse(path.read_text()) for path in sorted(SRC.rglob("*.py"))}
        self.classes: dict[str, list[ast.ClassDef]] = collections.defaultdict(list)
        self.aliases: dict[str, ast.expr] = {}
        self.typevars: set[str] = set()
        for tree in self.trees.values():
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self.classes[node.name].append(node)
                elif isinstance(node, ast.TypeAlias):
                    self.aliases[node.name.id] = node.value
                elif (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and _head(node.value.func) in {"TypeVar", "ParamSpec", "TypeVarTuple"}
                ):
                    self.typevars.update(t.id for t in node.targets if isinstance(t, ast.Name))

    def descends_from(self, name: str, roots: set[str], seen: frozenset[str] = frozenset()) -> bool:
        if name in roots:
            return True
        if name in seen:
            return False
        return any(
            self.descends_from(_head(base), roots, seen | {name})
            for cls in self.classes.get(name, [])
            for base in cls.bases
        )

    def is_requirement(self, name: str) -> bool:
        return self.descends_from(name, TAG_ROOTS | {"ServiceMarker"})


class _Scope:
    def __init__(self, index: _Index, renames: dict[str, str]) -> None:
        self.index = index
        self.renames = renames

    def classes_in(
        self, expr: ast.expr, params: frozenset[str], enclosing: str | None, depth: int = 0
    ) -> Iterator[str]:
        """The class names a requirement type is made of."""
        match expr:
            case ast.BinOp(op=ast.BitOr()):
                yield from self.classes_in(expr.left, params, enclosing, depth)
                yield from self.classes_in(expr.right, params, enclosing, depth)
            case ast.Constant(value=str() as text):
                yield from self.classes_in(ast.parse(text, mode="eval").body, params, enclosing)
            case ast.Subscript() | ast.Name() | ast.Attribute():
                name = _head(expr)
                if name in params or name in self.index.typevars or name in NOT_SERVICES:
                    return
                name = enclosing if name == "Self" and enclosing else self.renames.get(name, name)
                alias = self.index.aliases.get(name)
                if alias is not None and not self.index.is_requirement(name) and depth < 10:
                    yield from self.classes_in(alias, params, enclosing, depth + 1)
                else:
                    yield name
            case _:
                yield ast.unparse(expr)


def _param_name(param: ast.type_param) -> str:
    assert isinstance(param, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple)
    return param.name


@functools.cache
def _index() -> _Index:
    return _Index()


@functools.cache
def _required_classes() -> dict[str, list[str]]:
    """Each class named as a requirement, with where."""
    index = _index()
    found: dict[str, list[str]] = collections.defaultdict(list)

    def visit(node: ast.AST, scope: _Scope, params: frozenset[str], cls: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner_params, inner_cls = params, cls
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                inner_params = params | {_param_name(t) for t in child.type_params}
            if isinstance(child, ast.ClassDef):
                inner_cls = child.name
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.returns:
                returns = child.returns
                if isinstance(returns, ast.Constant) and isinstance(returns.value, str):
                    returns = ast.parse(returns.value, mode="eval").body
                for sub in ast.walk(returns):
                    if not isinstance(sub, ast.Subscript) or _head(sub) not in R_INDEX:
                        continue
                    args = sub.slice.elts if isinstance(sub.slice, ast.Tuple) else [sub.slice]
                    if len(args) > R_INDEX[_head(sub)]:
                        where = f"{rel}:{child.lineno}"
                        requirement = args[R_INDEX[_head(sub)]]
                        for name in scope.classes_in(requirement, inner_params, inner_cls):
                            found[name].append(where)
            visit(child, scope, inner_params, inner_cls)

    for path, tree in index.trees.items():
        rel = path.relative_to(SRC)
        renames = {
            alias.asname: alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.asname
        }
        visit(tree, _Scope(index, renames), frozenset(), None)
    return found


def _router_markers() -> set[str]:
    tree = ast.parse(ROUTER_MARKERS.read_text())
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def test_requirements_are_tags_or_service_markers() -> None:
    index = _index()
    router = _router_markers()
    missing = {
        name: places[:3]
        for name, places in _required_classes().items()
        if name not in router and not index.is_requirement(name)
    }
    assert not missing, (
        "a class required by a signature must be a Tag or subclass "
        f"pyfect.context.ServiceMarker, so router.serve passes it through: {missing}"
    )


def test_the_walk_finds_requirements() -> None:
    """The walk sees the tags, service markers and router markers that
    signatures require."""
    index = _index()
    markers = {name for name in _required_classes() if index.descends_from(name, {"ServiceMarker"})}
    assert {"HandlersFor", "HandlerOf"} <= markers
    assert {"Scope", "HttpRouter", "Generator", "Requires", "GlobalRaises"} <= set(
        _required_classes()
    )


def test_router_markers_are_not_service_markers() -> None:
    index = _index()
    router = _router_markers()
    assert router >= {"Requires", "Raises", "GlobalRequires", "GlobalRaises"}
    leaking = [name for name in router if index.is_requirement(name)]
    assert not leaking, f"router markers would leak through serve: {leaking}"


def test_service_markers_are_never_built() -> None:
    from pyfect.rpc.group import HandlersFor

    try:
        HandlersFor()
    except TypeError as error:
        assert "type-level marker" in str(error)
    else:
        raise AssertionError("a service marker was built")
