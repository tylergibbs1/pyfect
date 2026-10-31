"""Resource template URIs matched as Effect's ``makeUriMatcher`` matches
them (find-my-way, trailing and duplicate slashes ignored, case
sensitive): parameters percent-decoded, query and fragment left out (QA
ai-workflow MCP-3). Expected values are Effect 4.0.6's under Node."""

from __future__ import annotations

import pytest

from pyfect import schema as S
from pyfect.ai import mcp_server as M
from pyfect.ai.mcp_schema import param

_NOTES = M.uri_template("file:///notes/", S.String)
_PROFILE = M.uri_template("users://", param("id", S.String), "/profile")

CASES = [
    (_NOTES, "file:///notes/a", {"param0": "a"}),
    (_NOTES, "file:///notes/a%20b", {"param0": "a b"}),
    (_NOTES, "file:///notes/a%2Fb", {"param0": "a/b"}),
    (_NOTES, "file:///notes/a/", {"param0": "a"}),
    (_NOTES, "file:///notes/a?x=1", {"param0": "a"}),
    (_NOTES, "file:///notes//a", {"param0": "a"}),
    (_NOTES, "file:///notes/a#f", {"param0": "a"}),
    (_NOTES, "file:///notes/", None),
    (_NOTES, "file:///notes/a/b", None),
    (_NOTES, "file:///notes/%E2%82%AC", {"param0": "€"}),
    (_NOTES, "file:///notes/%ZZ", None),
    (_PROFILE, "users://1/profile", {"id": "1"}),
    (_PROFILE, "users://1/profile/", {"id": "1"}),
    (_PROFILE, "users://1/profileX", None),
    (_PROFILE, "users://1/2/profile", None),
]


@pytest.mark.parametrize(("template", "uri", "expected"), CASES, ids=[c[1] for c in CASES])
def test_matches_a_resource_uri_as_effect(
    template: M.UriTemplate[str], uri: str, expected: dict[str, str] | None
):
    assert template.match(uri) == expected
