"""An endpoint attribute named like a member of ``HttpApiGroup`` replaces that member, so the
class fails as it is created, and the docs list the names."""

from pathlib import Path
from types import new_class

import pytest

from pyfect.http_api import endpoint
from pyfect.http_api.group import RESERVED_NAMES, HttpApiGroup

GUIDE = Path(__file__).parent.parent / "website" / "content" / "docs" / "http-api.mdx"


@pytest.mark.parametrize("name", sorted(RESERVED_NAMES))
def test_an_endpoint_named_like_a_group_member_fails_at_class_creation(name: str):
    declared = endpoint.get("getUser", "/users")
    with pytest.raises(TypeError, match=rf"Users\.{name}.*reserved.*'getUser'"):
        new_class(
            "Users",
            (HttpApiGroup,),
            {"identifier": "users"},
            lambda ns: ns.update({name: declared}),
        )


def test_the_names_cover_every_public_member_of_the_group():
    public = {name for name in dir(HttpApiGroup) if not name.startswith("_")}
    assert public | {"identifier", "top_level", "endpoints", "annotations", "origin"} == set(
        RESERVED_NAMES
    )


def test_an_endpoint_whose_identifier_is_reserved_but_attribute_is_not_is_fine():
    class Items(HttpApiGroup, identifier="items"):
        add_item = endpoint.post("add", "/items")

    assert set(Items.endpoints) == {"add"}


def test_the_guide_lists_every_name():
    guide = GUIDE.read_text()
    missing = [name for name in sorted(RESERVED_NAMES) if f"`{name}`" not in guide]
    assert not missing
