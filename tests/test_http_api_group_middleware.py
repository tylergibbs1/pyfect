# Endpoints added with ``add`` are typed ``Any``; tests/type_checks.py pins the types.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A group declared ``HttpApiGroup[M]`` wraps every endpoint it serves in
``M``: the ones declared as attributes and the ones every class method
(``add``, ``prefix``, ...) brings in."""

from typing import Any, Never

import pytest
from oracle._http_api import api_layer, run_served

from pyfect import effect, layer, redacted
from pyfect import schema as S
from pyfect.http import client as http_client
from pyfect.http_api import api as api_module
from pyfect.http_api import builder, security
from pyfect.http_api import endpoint as ep
from pyfect.http_api import error as api_error
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import AnyGroup, HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware


class Gate(
    HttpApiMiddleware[Never, api_error.Unauthorized],
    key="test/Gate",
    security={"bearer": security.bearer},
):
    error = api_error.Unauthorized


class Admin(HttpApiGroup[Gate], identifier="admin"):
    a = ep.get("a", "/a", success=S.String)


def _derivations(group: type[Admin]) -> dict[str, type[Admin]]:
    wipe = ep.post("wipe", "/wipe", success=S.String)
    return {
        "add": group.add(wipe),
        "add replacing": group.add(ep.get("a", "/a2", success=S.String), wipe),
        "prefix after add": group.add(wipe).prefix("/v1"),
        "annotate after add": group.add(wipe).annotate_endpoints_merge(group.annotations),
    }


@pytest.mark.parametrize("name", list(_derivations(Admin)))
def test_every_derived_endpoint_carries_the_declared_middleware(name: str) -> None:
    derived = _derivations(Admin)[name]
    for endpoint in derived.endpoints.values():
        assert Gate in endpoint.middlewares, (name, endpoint.identifier)


def test_reflect_reports_the_declared_middleware_on_added_endpoints() -> None:
    group: AnyGroup = Admin.add(ep.post("wipe", "/wipe", success=S.String))
    seen: dict[str, Any] = {}
    api_module.reflect(
        HttpApi.make("X").add(group),
        on_group=lambda _group, _annotations: None,
        on_endpoint=lambda reflected: seen.__setitem__(
            reflected.endpoint.identifier, reflected.middleware
        ),
    )
    assert seen == {"a": (Gate,), "wipe": (Gate,)}


def test_an_added_endpoint_is_not_served_without_the_declared_middleware() -> None:
    group = Admin.add(ep.post("wipe", "/wipe", success=S.String))
    api = HttpApi.make("X").add(group)
    wiped: list[str] = []

    def wipe(_ctx: Any) -> Any:
        wiped.append("wiped")
        return effect.succeed("wiped")

    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["a"])(lambda _: effect.succeed("a")).handle(
            group.endpoints["wipe"]
        )(wipe),
    )

    def bearer(effect_: Any, options: Any) -> Any:
        if redacted.value(options.credential) == "ok":
            return effect_
        return effect.fail(api_error.Unauthorized())

    gate = layer.succeed(Gate, {"bearer": bearer})

    def program() -> Any:
        a = yield from http_client.get("/a")
        posted = yield from http_client.post("/wipe")
        return a.status, posted.status

    statuses = run_served(api_layer(api, live, gate), effect.gen(program))
    assert statuses == (401, 401)
    assert wiped == []


def test_group_endpoints_are_only_assigned_through_the_middleware_funnel() -> None:
    """Every ``endpoints`` assignment in group.py goes through ``_wrapped``
    (or keeps ``cls.endpoints``, already wrapped), so a new class method
    cannot bring in endpoints that skip the declared middleware."""
    import ast
    import inspect

    from pyfect.http_api import group as group_module

    tree = ast.parse(inspect.getsource(group_module))

    def funnelled(value: ast.expr) -> bool:
        if isinstance(value, ast.IfExp):
            return funnelled(value.body) and funnelled(value.orelse)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            return value.func.id == "_wrapped"
        return ast.unparse(value) == "cls.endpoints"

    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Attribute) and t.attr == "endpoints" for t in node.targets)
    ]
    assert len(assignments) >= 2
    for node in assignments:
        assert funnelled(node.value), ast.unparse(node)
