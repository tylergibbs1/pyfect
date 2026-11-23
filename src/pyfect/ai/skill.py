"""A standalone Agent Skill value for local agents and MCP servers (Effect's
``effect/ai/Skill``).

A ``Skill`` is an Agent Skill (https://agentskills.io/specification) as plain
data: validated YAML ``frontmatter``, markdown ``instructions`` and supporting
``files``, with ``SKILL.md`` as its file format (``to_files``, ``from_files``)::

    refunds = skill.make(
        frontmatter={"name": "refunds", "description": "Process customer refunds"},
        instructions="Read references/policy.md before issuing a refund.",
        files={"references/policy.md": "Refunds over $100 require approval."},
    )
    skill.to_files(refunds)["SKILL.md"]  # '---\\n"name": "refunds"\\n...'
    mcp_server.skill("skill://billing/refunds/SKILL.md", refunds)
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import NotRequired, TypedDict, cast

import typing_extensions

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import stringify
from pyfect._json_value import JsonValue
from pyfect.ai._mcp.skill_rules import is_safe_relative_path, split_skill_md
from pyfect.ai._mcp.skill_schema import (
    FRONTMATTER_COMPATIBILITY,
    FRONTMATTER_DESCRIPTION,
    FRONTMATTER_METADATA,
    FRONTMATTER_NAME,
)
from pyfect.effect import fail, suspend
from pyfect.errors import IllegalArgumentError
from pyfect.schema import ast
from pyfect.schema import transformation as T

Frontmatter = typing_extensions.TypedDict(
    "Frontmatter",
    {
        "name": str,
        "description": str,
        "license": NotRequired[str],
        "compatibility": NotRequired[str],
        "metadata": NotRequired[dict[str, str]],
        "allowed-tools": NotRequired[str],
    },
    extra_items=JsonValue,
)
"""The YAML frontmatter of a ``SKILL.md``, as the Agent Skills specification
defines it. ``name`` is 1 to 64 lowercase letters, digits and single hyphens
and names the skill's directory; ``description`` says what the skill does and
when to use it, in 1 to 1024 characters; ``compatibility`` is 1 to 500
characters; ``allowed-tools`` lists, space-separated, the tools the skill asks
to run without approval (hosts ignore it for a skill served over MCP unless
the user approved the grant). Other keys are kept unchanged."""

FRONTMATTER = S.Struct(
    Frontmatter,
    name=FRONTMATTER_NAME,
    description=FRONTMATTER_DESCRIPTION,
    compatibility=FRONTMATTER_COMPATIBILITY,
    metadata=FRONTMATTER_METADATA,
)
"""The schema of ``Frontmatter`` (Effect's ``Skill.Frontmatter``)."""

SkillFiles = typing_extensions.TypedDict("SkillFiles", {"SKILL.md": str}, extra_items=str | bytes)
"""A skill as files: its ``SKILL.md`` and its supporting files (``to_files``)."""

_DRIVE = re.compile(r"[A-Za-z]:")


def _is_safe_file_path(path: str) -> bool:
    return path != "SKILL.md" and _DRIVE.match(path) is None and is_safe_relative_path(path)


def _unsafe_path(files: Mapping[str, str | bytes]) -> str | bool:
    unsafe = next((path for path in files if not _is_safe_file_path(path)), None)
    return True if unsafe is None else f'Invalid skill file path "{unsafe}"'


class _Base64(TypedDict):
    base64: bytes


_BASE64 = S.Struct(_Base64, base64=S.BytesFromBase64)


def _unwrap(wrapped: _Base64) -> bytes:
    return wrapped["base64"]


def _wrap(content: bytes) -> _Base64:
    return {"base64": content}


def _bytes_json(_: tuple[ast.AST, ...]) -> ast.Link:
    # `{"base64": ...}` rather than a bare string, so text and bytes stay distinct.
    return ast.Link(_BASE64.ast, T.transform(decode=_unwrap, encode=_wrap))


_FILES = S.Record(S.String, S.Union(S.String, S.Bytes.annotate(to_codec_json=_bytes_json))).check(
    S.make_filter(_unsafe_path)
)


class Skill(S.Class, identifier="effect/ai/Skill"):
    """An Agent Skill: ``frontmatter``, markdown ``instructions`` and the
    supporting ``files``, keyed by paths under the skill's directory (never
    ``SKILL.md``, which ``to_files`` writes). Its JSON codec
    (``S.to_codec_json``) writes a file's bytes as ``{"base64": ...}``."""

    frontmatter: Frontmatter = S.field(FRONTMATTER)
    instructions: str
    files: Mapping[str, str | bytes] = S.field(_FILES)


def make(
    *,
    frontmatter: Frontmatter,
    instructions: str,
    files: Mapping[str, str | bytes] | None = None,
) -> Skill:
    """A validated ``Skill``. Raises ``SchemaError`` when the frontmatter is
    not valid Agent Skills frontmatter or a file's path is ``SKILL.md`` or
    leaves the skill; use ``from_files`` for untrusted input."""
    return Skill(frontmatter=frontmatter, instructions=instructions, files=dict(files or {}))


def to_files(skill: Skill, /) -> SkillFiles:
    """The skill as files: a ``SKILL.md`` holding its frontmatter and
    instructions, and its supporting files. Each frontmatter key and value
    is written as JSON, which YAML reads back unchanged (``from_files``)."""
    frontmatter = "\n".join(
        f"{stringify(key)}: {stringify(value)}" for key, value in skill.frontmatter.items()
    )
    files: dict[str, str | bytes] = {
        "SKILL.md": f"---\n{frontmatter}\n---\n\n{skill.instructions}",
        **skill.files,
    }
    return cast("SkillFiles", files)


_decode_skill = S.decode_unknown_effect(Skill)


def from_files(files: Mapping[str, str | bytes], /) -> Effect[Skill, IllegalArgumentError]:
    """The skill a ``SKILL.md`` and its supporting files hold. Fails with
    ``IllegalArgumentError`` when ``SKILL.md`` is missing, is not UTF-8,
    does not begin with YAML frontmatter, or the skill is not valid."""

    def parse() -> Effect[Skill, IllegalArgumentError]:
        supporting = dict(files)
        skill_md = supporting.pop("SKILL.md", None)
        if skill_md is None:
            return fail(IllegalArgumentError("Skill is missing SKILL.md"))
        if isinstance(skill_md, bytes):
            try:
                skill_md = skill_md.decode("utf-8")
            except UnicodeDecodeError:
                return fail(IllegalArgumentError("SKILL.md is not valid UTF-8"))
        split = split_skill_md(skill_md)
        if split is None:
            return fail(IllegalArgumentError("SKILL.md is missing valid YAML frontmatter"))
        frontmatter, instructions = split
        decoded = _decode_skill(
            {"frontmatter": frontmatter, "instructions": instructions, "files": supporting}
        )
        return decoded.map_error(lambda error: IllegalArgumentError(error.message))

    return suspend(parse)


__all__ = [
    "FRONTMATTER",
    "Frontmatter",
    "IllegalArgumentError",
    "Skill",
    "SkillFiles",
    "from_files",
    "make",
    "to_files",
]
