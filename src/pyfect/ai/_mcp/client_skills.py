"""The client side of the MCP Skills extension (SEP-2640): discovering a
server's skills and reading their files verified against the manifest
(the skills part of Effect's ``McpClient``)."""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.ai._mcp.client_discovery import (
    DiscoveryLimits,
    DiscoveryLimitsOptions,
    Request,
    check_cacheable,
    decode,
    paginate,
    resolve_limits,
)
from pyfect.ai._mcp.client_wire import failure
from pyfect.ai._mcp.skill_rules import (
    EXTENSION_ID,
    entry_problem,
    is_direct_child,
    is_skill_file,
    json_equal,
    parse_frontmatter,
)
from pyfect.ai._mcp.skill_schema import SKILL, Skill, SkillResource
from pyfect.ai.mcp_client_error import (
    ConfigurationError,
    McpClientError,
    UnsupportedError,
    ValidationError,
)
from pyfect.ai.mcp_schema import (
    READ_RESOURCE_RESULT,
    RESOURCE,
    ReadResourceResult,
    Resource,
    ServerCapabilities,
)
from pyfect.duration import Duration
from pyfect.effect import fail, gen, succeed
from pyfect.result import Err

type Deadline = Callable[
    [Effect[Any, McpClientError], str, Duration | None], Effect[Any, McpClientError]
]


@dataclass(frozen=True, slots=True)
class InvalidSkill:
    """A listed entry left out of ``list_skills``, and why."""

    entry: object
    error: McpClientError


type OnInvalidSkill = Callable[[InvalidSkill], Effect[None]]


class ClientExtensions(TypedDict, total=False):
    """The protocol extensions a client declares (Effect's ``extensions``)."""

    skills: bool
    """The Skills extension (SEP-2640), which the skill methods require."""


def client_capabilities(skills: bool) -> dict[str, Any]:
    """The capabilities a client declares: the extension only when enabled."""
    return {"extensions": {EXTENSION_ID: {}}} if skills else {}


class _SkillsPage(TypedDict):
    skills: list[object]
    nextCursor: NotRequired[str]


class _DirectoryPage(TypedDict):
    resources: list[object]
    nextCursor: NotRequired[str]


class _GetSkill(TypedDict):
    skill: object


_SKILLS_PAGE = S.Struct(_SkillsPage, skills=S.List(S.Unknown))
_DIRECTORY_PAGE = S.Struct(_DirectoryPage, resources=S.List(S.Unknown))
_GET_SKILL = S.Struct(_GetSkill, skill=S.Unknown)


def _invalid(description: str) -> Effect[Any, McpClientError]:
    return fail(failure(ValidationError(description)))


def _unsupported(description: str) -> Effect[Any, McpClientError]:
    return fail(failure(UnsupportedError(description)))


def _decode_skill(entry: object) -> Effect[Skill, McpClientError]:
    def checked(skill: Skill) -> Effect[Skill, McpClientError]:
        problem = entry_problem(skill)
        if problem is None:
            return succeed(skill)
        return _invalid(f"Invalid MCP skill {skill['uri']}: {problem}")

    return decode(SKILL, entry).flat_map(checked)


def _bytes_of(content: Any) -> bytes | None:
    if "text" in content:
        return text_encode(cast("str", content["text"]))
    try:
        return base64.b64decode(cast("str", content["blob"]), validate=True)
    except binascii.Error:
        return None


@dataclass(frozen=True, slots=True)
class SkillsClient:
    """The extension's methods of one connected client."""

    request: Request
    deadline: Deadline
    timeout: Duration
    capabilities: ServerCapabilities
    limits: DiscoveryLimits
    enabled: bool
    """Whether the client declared the extension (``extensions={"skills": True}``)."""
    modern: bool

    @property
    def _settings(self) -> object:
        return (self.capabilities.get("extensions") or {}).get(EXTENSION_ID)

    @property
    def _serves_skills(self) -> bool:
        # Hosts call the extension's methods only when the server declares it,
        # and the extension requires the resources capability.
        return isinstance(self._settings, dict) and self.capabilities.get("resources") is not None

    @property
    def _serves_directories(self) -> bool:
        settings = self._settings
        return self._serves_skills and cast("dict[str, Any]", settings).get("directoryRead") is True

    def _require_enabled(self) -> Effect[None, McpClientError]:
        if self.enabled:
            return succeed(None)
        return fail(
            failure(ConfigurationError('MCP skills methods require extensions={"skills": True}'))
        )

    def _page(
        self, schema: S.Top
    ) -> Callable[[dict[str, Any]], Effect[dict[str, Any], McpClientError]]:
        def decode_page(raw: dict[str, Any]) -> Effect[dict[str, Any], McpClientError]:
            return check_cacheable(self.modern, raw).and_then(decode(schema, raw))

        return decode_page

    def list_skills(
        self,
        timeout: Duration | None,
        limits: DiscoveryLimitsOptions | None,
        on_invalid_skill: OnInvalidSkill | None,
    ) -> Effect[list[Skill], McpClientError]:
        @gen
        def run():
            yield from self._require_enabled()
            bounds = yield from resolve_limits(limits, self.limits)
            if not self._serves_skills:
                return list[Skill]()
            entries: list[object] = yield from paginate(
                self.request,
                label="skills",
                method="skills/list",
                key="skills",
                params={},
                limits=bounds,
                decode_page=self._page(_SKILLS_PAGE),
            )
            # A catalog that changes between pages can list a skill twice; the first entry wins.
            skills: dict[str, Skill] = {}
            for entry in entries:
                decoded = yield from _decode_skill(entry).result()
                if isinstance(decoded, Err):
                    if on_invalid_skill is None:
                        return (yield from fail(decoded.error))
                    yield from on_invalid_skill(InvalidSkill(entry, decoded.error))
                    continue
                skills.setdefault(decoded.value["uri"], decoded.value)
            return list(skills.values())

        return self.deadline(run, "skills discovery", self.timeout if timeout is None else timeout)

    def get_skill(self, uri: str, timeout: Duration | None) -> Effect[Skill, McpClientError]:
        @gen
        def run():
            yield from self._require_enabled()
            if not self._serves_skills:
                return (yield from _unsupported("Server does not declare the MCP Skills extension"))
            raw = yield from self.request("skills/get", {"uri": uri}, None)
            yield from check_cacheable(self.modern, raw)
            result = yield from decode(_GET_SKILL, raw)
            skill = yield from _decode_skill(result["skill"])
            if skill["uri"] != uri:
                return (yield from _invalid(f"MCP server returned skill {skill['uri']} for {uri}"))
            return skill

        return self.deadline(run, "skills/get", timeout)

    def read_resource_directory(
        self, uri: str, timeout: Duration | None, limits: DiscoveryLimitsOptions | None
    ) -> Effect[list[Resource], McpClientError]:
        @gen
        def run():
            yield from self._require_enabled()
            bounds = yield from resolve_limits(limits, self.limits)
            if not self._serves_directories:
                return (
                    yield from _unsupported(
                        "Server does not declare directory reads for the MCP Skills extension"
                    )
                )
            entries: list[object] = yield from paginate(
                self.request,
                label="directory",
                method="resources/directory/read",
                key="resources",
                params={"uri": uri},
                limits=bounds,
                decode_page=self._page(_DIRECTORY_PAGE),
            )
            # A directory that changes between pages can list a child twice; the first entry wins.
            children: dict[str, Resource] = {}
            for entry in entries:
                child: Resource = yield from decode(RESOURCE, entry)
                if not is_direct_child(uri, child["uri"]):
                    return (
                        yield from _invalid(
                            f"{child['uri']} is not a child of the MCP directory {uri}"
                        )
                    )
                children.setdefault(child["uri"], child)
            return list(children.values())

        return self.deadline(
            run, "directory discovery", self.timeout if timeout is None else timeout
        )

    def read_skill_resource(
        self, skill: Skill, uri: str, timeout: Duration | None
    ) -> Effect[ReadResourceResult, McpClientError]:
        @gen
        def run():  # noqa: PLR0911
            yield from self._require_enabled()
            # A file missing from the manifest is a change to the skill, not a file to
            # trust. A dynamic skill has no manifest, so any file in its directory is read.
            resources = skill["resources"]
            manifest: list[SkillResource] | None = None if resources == "dynamic" else resources
            listed = (
                None if manifest is None else next((r for r in manifest if r["uri"] == uri), None)
            )
            if not is_skill_file(skill["uri"], uri) if manifest is None else listed is None:
                return (yield from _invalid(f"{uri} is not a file of the MCP skill {skill['uri']}"))
            if self.capabilities.get("resources") is None:
                return (yield from _unsupported("Server does not advertise resources"))
            raw = yield from self.request("resources/read", {"uri": uri}, None)
            yield from check_cacheable(self.modern, raw)
            result: ReadResourceResult = yield from decode(READ_RESOURCE_RESULT, raw)
            contents = result["contents"]
            if len(contents) != 1 or contents[0]["uri"] != uri:
                return (
                    yield from _invalid(f"MCP resources/read returned other contents than {uri}")
                )
            content = contents[0]
            data = _bytes_of(content)
            if data is None:
                return (yield from _invalid("Invalid MCP payload"))
            if listed is not None:
                digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
                if len(data) != listed["size"] or digest != listed["digest"]:
                    return (
                        yield from _invalid(
                            f"{uri} does not match the digest and size listed by the MCP skill "
                            f"{skill['uri']}"
                        )
                    )
            if uri != skill["uri"]:
                return result
            # Verified bytes can still carry other frontmatter than the listing, and
            # hosts must not load a skill whose two descriptions differ.
            text = content["text"] if "text" in content else data.decode("utf-8", "replace")
            frontmatter = parse_frontmatter(text)
            if frontmatter is not None and json_equal(frontmatter, skill["frontmatter"]):
                return result
            return (
                yield from _invalid(
                    f"The frontmatter of {uri} differs from the frontmatter listed "
                    "for the MCP skill"
                )
            )

        return self.deadline(run, "resources/read", timeout)
