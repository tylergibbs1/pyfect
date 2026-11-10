"""Registering an Agent Skill with the ``McpServer`` (Effect's
``McpServer.registerSkill``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect.ai._mcp.core import McpServer, ResourceEntry
from pyfect.ai._mcp.invoke import Invoke
from pyfect.ai._mcp.skills import SkillFileInput, SkillRegistration, make_static_skill
from pyfect.ai.mcp_schema import Resource
from pyfect.context import Context
from pyfect.effect import fail, gen, succeed
from pyfect.errors import IllegalArgumentError


def register_skill(
    uri: str,
    files: Mapping[str, SkillFileInput],
    *,
    annotations: Context[Never] | None = None,
) -> Effect[None, IllegalArgumentError, McpServer]:
    """Register an Agent Skill under the MCP Skills extension (SEP-2640).

    ``uri`` addresses its ``SKILL.md`` (``skill://<skill-path>/SKILL.md``),
    whose last path segment is the skill's name; ``files`` maps paths under
    the skill root to the files, ``SKILL.md`` included, served verbatim.
    Each file is a resource, ``skills/list`` and ``skills/get`` list the
    skill with every file's SHA-256 digest and size, and every directory of
    the namespace is readable with ``resources/directory/read``.

    Fails with ``IllegalArgumentError`` when the skill breaks the extension's
    rules (a name other than the URI's, a ``SKILL.md`` without YAML
    frontmatter, frontmatter that is not ``SKILL_FRONTMATTER``, a path
    leaving the skill, more than 512 files or 16 MiB), when its directory
    contains or lies in another skill's, or when one of its files is
    already a resource. Registering a resource at a skill file's URI later
    is a defect."""
    shown: Context[Any] = annotations or Context.empty()

    @gen
    def register():
        built = make_static_skill(uri, files)
        if isinstance(built, IllegalArgumentError):
            return (yield from fail(built))
        server = yield from McpServer()
        # Its handlers run under the middleware and services it was registered with.
        services: Context[Any] = yield from fx.context()
        invoke = Invoke.make(services, server.global_middleware)
        registration = SkillRegistration(built.entry, shown, built.directories, invoke)
        entries = [
            ResourceEntry(Resource(**file.resource), shown, succeed(file.result), services)
            for file in built.files
        ]
        yield from server.add_skill(registration, entries)

    return register
