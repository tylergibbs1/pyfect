"""The values of the MCP Skills extension (SEP-2640) that clients and servers
exchange: a skill's manifest entry, its files and its frontmatter (Effect's
``McpSchema.Skill``, ``SkillResource`` and ``SkillFrontmatter``).

Re-exported by ``pyfect.ai.mcp_schema``.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from pyfect import schema as S
from pyfect._json_value import JsonValue

_JSON_OBJECT = S.Record(S.String, S.Json)

# Python's ``$`` also matches before a final newline; ``\Z`` is JavaScript's ``$``.
_DIGEST = r"^sha256:[0-9a-f]{64}\Z"
_SKILL_NAME = r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z"


class SkillResource(TypedDict):
    """A file of a skill, with the SHA-256 digest and size of its bytes."""

    uri: str
    digest: str
    """``sha256:`` followed by 64 lowercase hexadecimal digits."""
    size: int


SKILL_RESOURCE = S.Struct(
    SkillResource, digest=S.String.check(S.is_pattern(_DIGEST)), size=S.Natural
)


_SkillFrontmatterFields = TypedDict(
    "_SkillFrontmatterFields",
    {
        "name": str,
        "description": str,
        "license": NotRequired[str],
        "compatibility": NotRequired[str],
        "metadata": NotRequired[dict[str, str]],
        "allowed-tools": NotRequired[str],
    },
)


type SkillFrontmatter = dict[str, JsonValue]
"""The YAML frontmatter of a ``SKILL.md`` as JSON. ``SKILL_FRONTMATTER``
checks the fields the Agent Skills specification defines (``name``,
``description``, ``license``, ``compatibility``, ``metadata``,
``allowed-tools``) and keeps the others unchanged."""

SKILL_FRONTMATTER = S.StructWithRest(
    S.Struct(
        _SkillFrontmatterFields,
        name=S.String.check(S.is_max_length(64), S.is_pattern(_SKILL_NAME)),
        description=S.String.check(S.is_non_empty(), S.is_max_length(1024)),
        compatibility=S.String.check(S.is_non_empty(), S.is_max_length(500)),
        metadata=S.Record(S.String, S.String),
    ),
    _JSON_OBJECT,
)
"""The frontmatter as the Agent Skills specification defines it
(https://agentskills.io/specification). ``mcp_server`` checks a skill
against it before serving it; a skill received from a server is only
checked for the ``name`` and ``description`` the extension requires."""


class _ListedFrontmatterFields(TypedDict):
    name: str
    description: str


_LISTED_FRONTMATTER = S.StructWithRest(S.Struct(_ListedFrontmatterFields), _JSON_OBJECT)


class Skill(TypedDict):
    """A skill as ``skills/list`` and ``skills/get`` describe it."""

    uri: str
    """The resource URI of the skill's ``SKILL.md``."""
    frontmatter: SkillFrontmatter
    resources: list[SkillResource] | Literal["dynamic"]
    """Every file, ``SKILL.md`` included, or ``"dynamic"`` when the server
    generates the skill's content and publishes no digests."""
    _meta: NotRequired[dict[str, JsonValue]]


SKILL = S.Struct(
    Skill,
    frontmatter=_LISTED_FRONTMATTER,
    resources=S.Union(S.List(SKILL_RESOURCE), S.Literal("dynamic")),
    _meta=_JSON_OBJECT,
)

__all__ = [
    "SKILL",
    "SKILL_FRONTMATTER",
    "SKILL_RESOURCE",
    "Skill",
    "SkillFrontmatter",
    "SkillResource",
]
