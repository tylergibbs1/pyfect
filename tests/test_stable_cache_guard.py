"""Module-level caches are filled through ``pyfect._stable_cache`` or under a lock.

``handler_tag`` cached one tag per RPC with ``found = d.get(k)`` then ``d[k] = make()``. Two
threads without the GIL each made a tag, the server's handler layer registered under one and
the server looked under the other ("Unknown request tag"). ``functools.cache`` has the same
race: callers racing on a key can keep different results. So a function writing into a
module- or class-level dict holds a lock, and a ``functools.cache`` or ``lru_cache`` is
listed below as caching values any copy of which serves (else use ``stable_cache``).
"""

from __future__ import annotations

import ast
import functools
import re

import _source

_MAPPINGS = frozenset(
    {
        "Counter",
        "Dict",
        "MutableMapping",
        "OrderedDict",
        "WeakKeyDictionary",
        "WeakValueDictionary",
        "defaultdict",
        "dict",
    }
)

UNLOCKED_WRITES_ALLOWED = {
    # Equal values: a caller keeping a copy another thread didn't store loses nothing.
    "ai/response.py::_tool_parts_cache": "schemas of a tool",
    "chat/chat_interaction.py::_wires": "codecs of a schema",
    "cluster/reply.py::_schemas": "schemas of an RPC's replies",
    "rpc/_rpc.py::_exit_schemas": "schemas of an RPC's exit",
    "workflow/durable_queue.py::_queue_schemas": "schemas of a queue's items",
    # Keyed by an object made just before the write, which no other thread can know yet.
    "graphql/resolver.py::_url_resolvers": "the resolver being made",
    "sql/client/_transaction.py::_buffers": "the transaction level being opened",
    "sql/client/_transaction.py::_outermost_scopes": "the transaction level being opened",
    "workflow/durable_deferred.py::_await_owners": "the instance copy being made",
}
"""Unlocked writes into module-level dicts, each with why a race can't hand two callers
different values that matter."""

FUNCTOOLS_CACHES_ALLOWED = {
    # Plain data, compared by value.
    "_binding_doc.py::_attribute_docs",
    "_effect_hash.py::_string",
    "_whatwg_url/_percent.py::_ascii_table",
    "_whatwg_url/_unicode.py::_tables",
    "_whatwg_url/_unicode.py::compositions",
    "case.py::_defaults",
    "chat/slack/_emoji.py::_table",
    "cluster/runner.py::_key_hash",
    "date_time/_intl/_data.py::_diff",
    "date_time/_intl/_data.py::_read",
    "date_time/_intl/_data.py::_resolved",
    "date_time/_intl/_data.py::locale_data",
    "date_time/_intl/_data.py::meta",
    "date_time/_intl/_daylight.py::_has_negative_save",
    "date_time/_intl/_format.py::_generator",
    "date_time/_intl/_locale.py::_resolve",
    "date_time/_zones.py::_aliases",
    "date_time/_zones.py::_canonical_ids",
    "encoding/schema_binary/_fingerprint.py::_fingerprint_mode",
    "http/_httpcore_backend.py::_internals",
    "http/mime/__init__.py::_tables",
    "schema/_ecma_pattern.py::compile_ecma",
    # Schemas, codecs and compiled forms of them: any copy encodes and decodes the same.
    "encoding/schema_binary/_target.py::_compile_target_from_ast",
    "encoding/schema_binary/_target.py::make_codec",
    "encoding/schema_binary/_target.py::make_direct_codec",
    "encoding/schema_binary/_target.py::make_strict_codec",
    "http_api/_client_payload.py::_body_schema",
    "http_api/endpoint.py::_json_codec",
    "http_api/endpoint.py::_string_tree_codec",
    "http_api/endpoint.py::transform_response",
    "schema/_error_instance.py::_defect_schema",
    "schema/_error_instance.py::error_schema",
}
"""``functools.cache`` and ``lru_cache`` functions whose results any copy of serves."""


def _root_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _mapping_names(body: list[ast.stmt]) -> set[str]:
    """The names ``body`` binds to a dict (by annotation or value)."""
    names: set[str] = set()
    for statement in body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target, kinds = statement.target.id, [statement.annotation, statement.value]
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            target, kinds = statement.targets[0].id, [statement.value]
        else:
            continue
        for kind in kinds:
            if isinstance(kind, ast.Dict | ast.DictComp) or (
                kind is not None and _root_name(kind) in _MAPPINGS
            ):
                names.add(target)
    return names


def _is_lock(item: ast.withitem) -> bool:
    name = _root_name(item.context_expr)
    return name is not None and "lock" in name.lower()


class _Writes(ast.NodeVisitor):
    """Writes into a module- or class-level dict made in a function and not under a lock."""

    def __init__(self, module: ast.Module) -> None:
        self.module_maps = _mapping_names(module.body)
        self.class_maps = {
            node.name: _mapping_names(node.body)
            for node in ast.walk(module)
            if isinstance(node, ast.ClassDef)
        }
        self.found: list[tuple[str, int]] = []
        self._in_function = 0
        self._locked = 0

    def _shared(self, target: ast.expr) -> str | None:
        if not isinstance(target, ast.Subscript):
            return None
        mapping = target.value
        if isinstance(mapping, ast.Name) and mapping.id in self.module_maps:
            return mapping.id
        if isinstance(mapping, ast.Attribute) and isinstance(mapping.value, ast.Name):
            owner = mapping.value.id
            names = (
                {n for ns in self.class_maps.values() for n in ns}
                if owner == "cls"
                else (self.class_maps.get(owner, set()))
            )
            if mapping.attr in names:
                return f"{owner}.{mapping.attr}"
        return None

    def _check(self, targets: list[ast.expr], line: int) -> None:
        if self._in_function and not self._locked:
            for target in targets:
                name = self._shared(target)
                if name is not None:
                    self.found.append((name, line))

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._in_function += 1
        self.generic_visit(node)
        self._in_function -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        locked = any(_is_lock(item) for item in node.items)
        self._locked += locked
        self.generic_visit(node)
        self._locked -= locked

    visit_AsyncWith = visit_With

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check(node.targets, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check([node.target], node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check([node.target], node.lineno)
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        self._check(node.targets, node.lineno)
        self.generic_visit(node)


def unlocked_writes(module: ast.Module) -> list[tuple[str, int]]:
    writes = _Writes(module)
    writes.visit(module)
    return writes.found


def _is_functools_cache(node: ast.expr) -> bool:
    return _root_name(node) in {"cache", "lru_cache"}


def functools_caches(module: ast.Module) -> list[tuple[str, int]]:
    """The functions ``module`` caches with ``functools.cache`` or ``lru_cache``."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
            _is_functools_cache(d) for d in node.decorator_list
        ):
            found.append((node.name, node.lineno))
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and _is_functools_cache(node.value.func)
        ):
            found.append((node.targets[0].id, node.lineno))
    return found


_MAPPING = "|".join(sorted(_MAPPINGS))
_DEFINES_MAPPING = (
    rf"(?: *: *(?:ClassVar\[)?[\w.]*(?:{_MAPPING})\b"  # annotated as a dict
    rf"|(?: *:[^\n=]*)? *= *(?:\{{|[\w.]*(?:{_MAPPING})\())"  # or made one
)
_DEFINITION = re.compile(rf"^( {4})?(\w+){_DEFINES_MAPPING}", re.MULTILINE)
_INDEXED_TARGET = re.compile(
    r"(?:^[ \t]+(?:del[ \t]+)?|= *)((?:cls\.|[A-Z]\w*\.)?\w+)\[", re.MULTILINE
)
_FUNCTOOLS_CACHE = re.compile(
    r"^ *@(?:functools\.)?(?:cache|lru_cache)\b|= *(?:functools\.)?(?:cache|lru_cache)\(",
    re.MULTILINE,
)


def _may_write(source: str) -> bool:
    """Whether ``source`` may write into a module- or class-level dict in a function: a cheap
    skip before parsing (a parse of every file in src takes seconds)."""
    found = _DEFINITION.findall(source)
    names = {name for indent, name in found if not indent}
    in_class = any(indent for indent, _ in found)
    if not names and not in_class:
        return False
    targets = set(_INDEXED_TARGET.findall(source))
    return not targets.isdisjoint(names) or (in_class and any("." in t for t in targets))


def _may_cache(source: str) -> bool:
    return "cache" in source and _FUNCTOOLS_CACHE.search(source) is not None


@functools.cache
def _found() -> tuple[dict[str, str], dict[str, str]]:
    """Every unlocked write and every functools cache in src, by allowlist key, each with
    where it is."""
    writes: dict[str, str] = {}
    caches: dict[str, str] = {}
    for path in _source.files(_source.SRC):
        source = _source.folded(path)
        where = path.relative_to(_source.SRC).as_posix()
        if _may_write(source):
            for name, line in unlocked_writes(_source.tree(path)):
                writes.setdefault(f"{where}::{name}", f"{where}:{line}")
        if _may_cache(source):
            for name, line in functools_caches(_source.tree(path)):
                caches.setdefault(f"{where}::{name}", f"{where}:{line}")
    return writes, caches


def test_module_level_dicts_are_written_under_a_lock_or_through_a_stable_cache() -> None:
    found = [where for key, where in _found()[0].items() if key not in UNLOCKED_WRITES_ALLOWED]
    assert not found, (
        "a cache two threads may fill at once: use pyfect._stable_cache.StableCache, hold a "
        f"lock, or list it in UNLOCKED_WRITES_ALLOWED with why a race is harmless: {found}"
    )


def test_functools_caches_are_listed_as_caching_interchangeable_values() -> None:
    found = [where for key, where in _found()[1].items() if key not in FUNCTOOLS_CACHES_ALLOWED]
    assert not found, (
        "functools.cache may hand racing threads different results: use "
        "pyfect._stable_cache.stable_cache when the result's identity matters, else list it "
        f"in FUNCTOOLS_CACHES_ALLOWED: {found}"
    )


def test_the_allowlists_name_only_what_is_there() -> None:
    writes, caches = _found()
    stale = (set(UNLOCKED_WRITES_ALLOWED) - set(writes)) | (FUNCTOOLS_CACHES_ALLOWED - set(caches))
    assert not stale, stale


_GUARDED = """
import functools, threading, weakref
_tags: dict[str, type] = {}
_weak = weakref.WeakKeyDictionary()
_lock = threading.Lock()
_flag = [False]

def tag(key):
    found = _tags.get(key)
    if found is None:
        found = _tags[key] = type(key, (), {})
    return found

def locked(key):
    with _lock:
        _tags[key] = 1

def weak(key):
    _weak[key] += 1
    del _weak[key]
    _flag[0] = True

class Registry:
    _by_name: dict[str, int] = {}

    @classmethod
    def add(cls, name):
        cls._by_name[name] = 1
        Registry._by_name[name] = 2

_tags["at import"] = int

@functools.cache
def a(): ...

@functools.lru_cache(maxsize=4)
def b(): ...

c = functools.lru_cache(maxsize=4)(len)
"""


def test_the_guard_sees_unlocked_writes_and_functools_caches() -> None:
    module = _source.parse(_GUARDED)
    assert unlocked_writes(module) == [
        ("_tags", 11),
        ("_weak", 19),
        ("_weak", 20),
        ("cls._by_name", 28),
        ("Registry._by_name", 29),
    ]
    assert [name for name, _ in functools_caches(module)] == ["a", "b", "c"]
