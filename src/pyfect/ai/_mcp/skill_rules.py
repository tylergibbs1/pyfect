"""The rules of the MCP Skills extension (SEP-2640) that both sides check:
a skill's URI and paths, its ``SKILL.md`` frontmatter and its manifest
(Effect's ``internal/mcpSkills.ts``).

https://github.com/modelcontextprotocol/ext-skills/blob/main/specification/stable/skills.mdx
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, cast

from pyfect.ai._mcp.skill_schema import Skill, SkillFrontmatter
from pyfect.encoding import yaml

EXTENSION_ID = "io.modelcontextprotocol/skills"
_SKILL_MD = "/SKILL.md"

_FRONTMATTER = re.compile(r"﻿?---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|\Z)")
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def is_safe_relative_path(path: str) -> bool:
    """A path with no empty, ``.`` or ``..`` segment and no backslash."""
    return (
        path != ""
        and "\\" not in path
        and all(segment not in ("", ".", "..") for segment in path.split("/"))
    )


def is_skill_name(name: str) -> bool:
    """The Agent Skills ``name`` rule: lowercase letters, digits and single
    hyphens, neither leading nor trailing, at most 64 characters."""
    return len(name) <= 64 and _SKILL_NAME.fullmatch(name) is not None


def _as_json(value: object) -> object:
    """``value`` as JSON carries it: ``.inf`` and ``.nan`` become ``None``."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _as_json(item) for key, item in cast("dict[str, object]", value).items()}
    if isinstance(value, list):
        return [_as_json(item) for item in cast("list[object]", value)]
    return value


def parse_frontmatter(markdown: str) -> SkillFrontmatter | None:
    """The YAML frontmatter of a ``SKILL.md``, or ``None`` when the file does
    not begin with a frontmatter block holding a YAML mapping."""
    found = _FRONTMATTER.match(markdown)
    if found is None:
        return None
    try:
        parsed = yaml.parse(found.group(1))
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return cast("SkillFrontmatter", _as_json(cast("dict[str, object]", parsed)))


def json_equal(a: object, b: object) -> bool:
    """Structural equality of JSON values, where ``True`` is not ``1``."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, dict) and isinstance(b, dict):
        left = cast("dict[str, object]", a)
        right = cast("dict[str, object]", b)
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(a, list) and isinstance(b, list):
        left_items = cast("list[object]", a)
        right_items = cast("list[object]", b)
        return len(left_items) == len(right_items) and all(
            json_equal(x, y) for x, y in zip(left_items, right_items, strict=True)
        )
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    return type(cast("object", a)) is type(b) and a == b


def js_order(text: str) -> bytes:
    """``text`` 's UTF-16 code units: a sort key ordering strings as
    JavaScript's ``<`` does, two bytes per unit of JavaScript's ``length``."""
    return text.encode("utf-16-be", "surrogatepass")


def skill_root(uri: str) -> str:
    """The directory holding a skill's ``SKILL.md``, given the ``SKILL.md`` URI."""
    return uri[: -len(_SKILL_MD)]


def is_skill_file(skill_uri: str, uri: str) -> bool:
    """Whether ``uri`` addresses a file inside the skill whose ``SKILL.md``
    is at ``skill_uri``."""
    root = skill_root(skill_uri)
    return uri.startswith(f"{root}/") and is_safe_relative_path(uri[len(root) + 1 :])


def is_direct_child(directory: str, child: str) -> bool:
    """Whether ``child`` is a direct child of the directory at ``directory``."""
    if not child.startswith(f"{directory}/"):
        return False
    name = child[len(directory) + 1 :]
    return name not in ("", ".", "..") and "/" not in name


def entry_problem(entry: Skill) -> str | None:  # noqa: PLR0911
    """Why a skill received from a server breaks the extension's rules, or
    ``None`` when it is valid. Hosts must not load an invalid entry. The
    digest and size formats are checked by ``SKILL``."""
    uri = entry["uri"]
    scheme_end = uri.find("://")
    if scheme_end <= 0 or not uri.endswith(_SKILL_MD):
        return "the URI does not address a SKILL.md"
    skill_path = skill_root(uri)[scheme_end + 3 :]
    if not is_safe_relative_path(skill_path):
        return "the skill path has an empty, '.' or '..' segment"
    name = skill_path.split("/")[-1]
    frontmatter: Mapping[str, Any] = entry["frontmatter"]
    if frontmatter.get("name") != name or not is_skill_name(name):
        return f'the frontmatter name must equal "{name}" and follow the Agent Skills naming rules'
    description = frontmatter.get("description")
    if not isinstance(description, str) or description == "" or len(js_order(description)) > 2048:
        return "the frontmatter description must be a string of 1 to 1024 characters"
    resources = entry["resources"]
    if resources == "dynamic":
        return None
    uris: set[str] = set()
    for resource in resources:
        file = resource["uri"]
        if not is_skill_file(uri, file):
            return f"{file} is not a file of the skill"
        if file in uris:
            return f"{file} is listed twice"
        uris.add(file)
    return None if uri in uris else "the manifest does not list SKILL.md"
