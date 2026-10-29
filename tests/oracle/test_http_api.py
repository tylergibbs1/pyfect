"""Ports of Effect's ``httpapi/HttpApi.test.ts``. Each test's docstring is
the Effect test title.

Omitted: "does not add inherited groups" (a JavaScript prototype chain;
a Python mapping has no inherited keys).
"""

from pyfect.http_api import endpoint as ep
from pyfect.http_api import openapi
from pyfect.http_api.api import HttpApi, reflect
from pyfect.http_api.group import HttpApiGroup


def test_stores_the_supplied_identifier() -> None:
    """stores the supplied identifier"""
    assert HttpApi.make("Api").identifier == "Api"


def test_initializes_groups_as_a_readonly_record() -> None:
    """initializes groups as a readonly record"""
    assert dict(HttpApi.make("Api").groups) == {}


def test_stores_proto_group_and_endpoint_identifiers_as_own_properties() -> None:
    """stores __proto__ group and endpoint identifiers as own properties"""
    group = HttpApiGroup.make("__proto__").add(ep.get("__proto__", "/proto"))
    child = HttpApi.make("Child").add(group)
    api = HttpApi.make("Api").add_http_api(child)
    assert "__proto__" in group.endpoints
    assert "__proto__" in child.groups
    assert "__proto__" in api.groups
    assert "__proto__" in api.groups["__proto__"].endpoints
    reflected: list[str] = []
    reflect(
        api,
        on_group=lambda g, _annotations: reflected.append(g.identifier),
        on_endpoint=lambda e: reflected.append(e.endpoint.identifier),
    )
    assert reflected == ["__proto__", "__proto__"]


def test_does_not_mutate_groups_from_the_added_api() -> None:
    """does not mutate groups from the added API"""
    group = HttpApiGroup.make("users").annotate(openapi.Title, "Users")
    child = HttpApi.make("Child").annotate(openapi.Description, "Child API").add(group)
    original = group.annotations
    parent = HttpApi.make("Parent").add_http_api(child)
    assert group.annotations is original
    assert child.groups["users"] is group
    assert parent.groups["users"] is not group
    assert parent.groups["users"].annotations.get(openapi.Title) == "Users"
    assert parent.groups["users"].annotations.get(openapi.Description) == "Child API"


def _tag(api: HttpApi[object], name: str) -> dict[str, str]:
    return next(tag for tag in openapi.from_api(api)["tags"] if tag["name"] == name)


def test_keeps_annotations_from_api_variants_isolated() -> None:
    """keeps annotations from API variants isolated"""
    group = HttpApiGroup.make("users").annotate(openapi.Title, "Users")
    child = HttpApi.make("Child").add(group)
    public = HttpApi.make("PublicParent").add_http_api(
        child.annotate(openapi.Description, "Public API")
    )
    internal = HttpApi.make("InternalParent").add_http_api(
        child.annotate(openapi.Description, "Internal API")
    )
    assert public.groups["users"].annotations.get(openapi.Description) == "Public API"
    assert internal.groups["users"].annotations.get(openapi.Description) == "Internal API"
    assert public.groups["users"] is not internal.groups["users"]
    assert _tag(public, "Users")["description"] == "Public API"
    assert _tag(internal, "Users")["description"] == "Internal API"


def test_preserves_group_annotation_precedence() -> None:
    """preserves group annotation precedence"""
    group = HttpApiGroup.make("users").annotate(openapi.Title, "Group title")
    child = HttpApi.make("Child").annotate(openapi.Title, "API title").add(group)
    parent = HttpApi.make("Parent").add_http_api(child)
    assert parent.groups["users"].annotations.get(openapi.Title) == "Group title"
