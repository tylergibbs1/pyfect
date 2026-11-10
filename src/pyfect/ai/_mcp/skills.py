"""The server side of the MCP Skills extension (SEP-2640): a static skill's
manifest and directory tree, the catalog of registered skills, and the
``skills/list``, ``skills/get`` and ``resources/directory/read`` handlers
(Effect's ``internal/mcpSkills.ts`` and the skills part of ``mcpCore.ts``).
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Buffer, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect._json_text import stringify
from pyfect.ai._mcp.invoke import Invoke, RequestRejected
from pyfect.ai._mcp.skill_rules import (
    EXTENSION_ID,
    is_safe_relative_path,
    js_order,
    parse_frontmatter,
    skill_root,
)
from pyfect.ai._mcp.skill_schema import SKILL_FRONTMATTER, Skill, SkillResource
from pyfect.ai.mcp_schema import (
    METHOD_NOT_FOUND_ERROR_CODE,
    REQUEST_META_OBJECT,
    InvalidParams,
    JsonObject,
    McpError,
    McpRequestContext,
    ProtocolError,
    ReadResourceResult,
)
from pyfect.context import Context
from pyfect.effect import fail, gen, succeed
from pyfect.errors import IllegalArgumentError
from pyfect.http import mime

METHODS = frozenset({"skills/list", "skills/get", "resources/directory/read"})
"""The extension's methods, served while any skill is registered."""

_DIRECTORY_MIME_TYPE = "inode/directory"
MAX_FILES_PER_SKILL = 512
MAX_BYTES_PER_SKILL = 16 * 1024 * 1024
_TEXTUAL_APPLICATION_TYPES = frozenset({"application/json", "application/yaml", "image/svg+xml"})
_TYPESCRIPT = re.compile(r"\.ts\Z", re.IGNORECASE)


def declare_extension(extensions: dict[str, Any], serves_skills: bool) -> dict[str, Any]:
    """``extensions`` with the Skills extension declared while a skill is
    registered: it commits the server to its methods, directory reads included."""
    if not serves_skills:
        return extensions
    return {**extensions, EXTENSION_ID: {"directoryRead": True}}


# --- static skills ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillFile:
    """A file of a skill with an explicit MIME type (else inferred from its
    extension)."""

    content: str | Buffer
    mime_type: str | None = None


type SkillFileInput = str | Buffer | SkillFile
"""A file of a skill: its text, its bytes, or either with a MIME type."""


class DirectoryChild(TypedDict):
    """A ``resources/directory/read`` child: a file with the metadata
    ``resources/list`` gives it, or a subdirectory (``inode/directory``)."""

    uri: str
    name: str
    mimeType: str
    description: NotRequired[str]
    size: NotRequired[int]


@dataclass(frozen=True, slots=True)
class ServedFile:
    resource: DirectoryChild
    result: ReadResourceResult


@dataclass(frozen=True, slots=True)
class StaticSkill:
    entry: Skill
    files: tuple[ServedFile, ...]
    directories: Mapping[str, tuple[DirectoryChild, ...]]
    """Each directory URI, from the namespace root down, to its direct children."""


def mime_type_for(path: str) -> str:
    # The standard table maps `.ts` to MPEG transport streams, but a skill's
    # `.ts` files are TypeScript scripts.
    if _TYPESCRIPT.search(path) is not None:
        return "text/x-typescript"
    return mime.get_type(path) or "application/octet-stream"


def _decode_text(mime_type: str, content: bytes) -> str | None:
    """The text of a textual file that is valid UTF-8 (a BOM kept, so the text
    encodes back to the digested bytes), else ``None``: served as a blob."""
    if not mime_type.startswith("text/") and mime_type not in _TEXTUAL_APPLICATION_TYPES:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _bytes_of(file: SkillFileInput) -> tuple[bytes, str | None]:
    """A copy of the file's bytes, so a caller changing its buffer later
    cannot change what is served under the listed digest."""
    content, mime_type = (
        (file.content, file.mime_type) if isinstance(file, SkillFile) else (file, None)
    )
    return (text_encode(content) if isinstance(content, str) else bytes(content)), mime_type


def _frontmatter_problem(frontmatter: object) -> str | None:
    try:
        S.decode_unknown_sync(SKILL_FRONTMATTER)(frontmatter)
    except S.SchemaError as error:
        return error.message
    return None


def make_static_skill(  # noqa: PLR0911
    uri: str, files: Mapping[str, SkillFileInput]
) -> StaticSkill | IllegalArgumentError:
    """Validate a skill against the extension's server rules and precompute
    what the protocol serves: the manifest, with digests of the bytes served,
    each file's resource, and the directory tree from the namespace root."""

    def failed(reason: str) -> IllegalArgumentError:
        return IllegalArgumentError(f"Skill {uri}: {reason}")

    scheme_end = uri.find("://")
    if scheme_end <= 0 or not uri.endswith("/SKILL.md"):
        return failed("the URI must have the form <scheme>://<skill-path>/SKILL.md")
    scheme = uri[: scheme_end + 3]
    skill_path = skill_root(uri)[len(scheme) :]
    if not is_safe_relative_path(skill_path):
        return failed("the skill path must have no empty, '.' or '..' segment")
    name = skill_path.split("/")[-1]
    if len(files) > MAX_FILES_PER_SKILL:
        return failed(f"it has {len(files)} files; the limit is {MAX_FILES_PER_SKILL}")
    sources = {path: _bytes_of(file) for path, file in files.items()}
    total = sum(len(content) for content, _ in sources.values())
    if total > MAX_BYTES_PER_SKILL:
        return failed(f"it has {total} bytes; the limit is {MAX_BYTES_PER_SKILL}")
    for path in sources:
        if not is_safe_relative_path(path):
            return failed(f'the file path "{path}" escapes the skill')
    skill_md = sources.get("SKILL.md")
    if skill_md is None:
        return failed("SKILL.md is missing")

    # The listed frontmatter is parsed from the served SKILL.md, so the two
    # cannot differ.
    frontmatter = parse_frontmatter(_decode_text("text/markdown", skill_md[0]) or "")
    if frontmatter is None:
        return failed("SKILL.md must begin with YAML frontmatter holding a mapping")
    if frontmatter.get("name") != name:
        listed = stringify(frontmatter["name"]) if "name" in frontmatter else "undefined"
        return failed(f'the frontmatter name {listed} must equal "{name}"')
    # A skill served over MCP must conform to the Agent Skills specification.
    problem = _frontmatter_problem(frontmatter)
    if problem is not None:
        return failed(f"the frontmatter is not valid Agent Skills frontmatter: {problem}")
    description = cast("str", frontmatter["description"])

    resources: list[SkillResource] = []
    served: list[ServedFile] = []
    children: dict[str, dict[str, DirectoryChild]] = {}
    for path in sorted(sources, key=js_order):
        content, given_type = sources[path]
        file_uri = f"{scheme}{skill_path}/{path}"
        mime_type = given_type or mime_type_for(path)
        size = len(content)
        resource: DirectoryChild = (
            {
                "uri": file_uri,
                "name": name,
                "description": description,
                "mimeType": mime_type,
                "size": size,
            }
            if path == "SKILL.md"
            else {
                "uri": file_uri,
                "name": path.rsplit("/", maxsplit=1)[-1],
                "mimeType": mime_type,
                "size": size,
            }
        )
        text = _decode_text(mime_type, content)
        served.append(ServedFile(resource, _contents(file_uri, mime_type, content, text)))
        digest = hashlib.sha256(content).hexdigest()
        resources.append({"uri": file_uri, "digest": f"sha256:{digest}", "size": size})

        # Every directory from the namespace root down is readable, including
        # the prefix directories above the skill root.
        segments = f"{skill_path}/{path}".split("/")
        for depth in range(1, len(segments)):
            directory = f"{scheme}{'/'.join(segments[:depth])}"
            child: DirectoryChild = (
                resource
                if depth == len(segments) - 1
                else {
                    "uri": f"{scheme}{'/'.join(segments[: depth + 1])}",
                    "name": segments[depth],
                    "mimeType": _DIRECTORY_MIME_TYPE,
                }
            )
            children.setdefault(directory, {})[child["uri"]] = child

    entry: Skill = {"uri": uri, "frontmatter": frontmatter, "resources": resources}
    directories = {directory: tuple(found.values()) for directory, found in children.items()}
    return StaticSkill(entry, tuple(served), directories)


def _contents(uri: str, mime_type: str, content: bytes, text: str | None) -> ReadResourceResult:
    if text is not None:
        return {"contents": [{"uri": uri, "mimeType": mime_type, "text": text}]}
    blob = base64.b64encode(content).decode("ascii")
    return {"contents": [{"uri": uri, "mimeType": mime_type, "blob": blob}]}


# --- the catalog ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillRegistration:
    entry: Skill
    annotations: Context[Any]
    directories: Mapping[str, tuple[DirectoryChild, ...]]
    invoke: Invoke
    """Runs the middleware the skill was registered under, with its
    SKILL.md URI as the target."""

    @property
    def files(self) -> tuple[str, ...]:
        resources = self.entry["resources"]
        return () if resources == "dynamic" else tuple(r["uri"] for r in resources)


def _overlap(a: str, b: str) -> bool:
    """Whether one skill directory contains the other, or both are the same."""
    root_a, root_b = skill_root(a), skill_root(b)
    return root_a == root_b or root_a.startswith(f"{root_b}/") or root_b.startswith(f"{root_a}/")


type Enabled = Callable[[Context[Any]], bool]
"""Whether a registration with these annotations is enabled for the request."""

type Checked[A] = Effect[A, McpError | RequestRejected, McpRequestContext]


class SkillCatalog:
    """The registered skills, by the URI of their ``SKILL.md``, and the file
    URIs they own."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillRegistration] = {}
        self._files: set[str] = set()

    @property
    def present(self) -> bool:
        return bool(self._skills)

    def owns_file(self, uri: str) -> bool:
        """Whether ``uri`` is a file of a registered skill, which only that
        skill may serve."""
        return uri in self._files

    def register(
        self, registration: SkillRegistration, resources: Iterable[str]
    ) -> IllegalArgumentError | None:
        """Claim the skill's URI and files, unless its directory overlaps
        another skill's or one of its files is a registered resource (one of
        ``resources``)."""
        uri = registration.entry["uri"]
        for other in self._skills:
            if _overlap(uri, other):
                return IllegalArgumentError(
                    f"Skill {uri}: its directory overlaps the skill {other}"
                )
        registered = set(resources)
        for file in registration.files:
            if file in registered:
                return IllegalArgumentError(
                    f"Skill {uri}: {file} is already registered as a resource"
                )
        self._skills[uri] = registration
        self._files.update(registration.files)
        return None

    def list(self, enabled: Enabled) -> Checked[list[Skill]]:
        """The enabled skills each visibility check shows, in registration order."""

        @gen
        def run():
            shown: list[Skill] = []
            for uri, registration in list(self._skills.items()):
                if not enabled(registration.annotations):
                    continue
                if (yield from registration.invoke.visible("skills/list", uri)):
                    shown.append(registration.entry)
            return shown

        return run

    def get(self, uri: str, enabled: Enabled) -> Checked[Skill]:
        not_found = InvalidParams(f"Skill '{uri}' not found")
        registration = self._skills.get(uri)
        if registration is None or not enabled(registration.annotations):
            return fail(not_found)
        return registration.invoke(
            succeed(registration.entry),
            method="skills/get",
            target=uri,
            payload={"uri": uri},
            hidden=not_found,
        )

    def read_directory(self, uri: str, enabled: Enabled) -> Checked[list[DirectoryChild]]:
        """The union of the children each shown skill has at ``uri``, in URI
        order; not found when none has the directory."""

        @gen
        def run():
            children: dict[str, DirectoryChild] = {}
            found = False
            for skill_uri, registration in list(self._skills.items()):
                own = registration.directories.get(uri)
                if own is None or not enabled(registration.annotations):
                    continue
                if not (
                    yield from registration.invoke.visible("resources/directory/read", skill_uri)
                ):
                    continue
                found = True
                for child in own:
                    children[child["uri"]] = child
            if not found:
                return (yield from fail(InvalidParams(f"Directory '{uri}' not found")))
            return sorted(children.values(), key=lambda child: js_order(child["uri"]))

        return run


# --- handlers -------------------------------------------------------------------------


class _Paginated(TypedDict):
    cursor: NotRequired[str]
    _meta: NotRequired[JsonObject]


class _Get(TypedDict):
    uri: str
    _meta: NotRequired[JsonObject]


class _ReadDirectory(TypedDict):
    uri: str
    cursor: NotRequired[str]
    _meta: NotRequired[JsonObject]


_LIST_PARAMS = S.Struct(_Paginated, _meta=REQUEST_META_OBJECT)
_GET_PARAMS = S.Struct(_Get, _meta=REQUEST_META_OBJECT)
_READ_DIRECTORY_PARAMS = S.Struct(_ReadDirectory, _meta=REQUEST_META_OBJECT)


def method_not_found(method: str) -> McpError:
    return ProtocolError(f"Method not found: {method}", error_code=METHOD_NOT_FOUND_ERROR_CODE)


def _decoded(schema: S.Top, params: object) -> Any | InvalidParams:
    try:
        return S.decode_unknown_sync(cast("Any", schema))(params)
    except S.SchemaError as error:
        return InvalidParams(error.message)


def serve(
    catalog: SkillCatalog, method: str, params: JsonObject, enabled: Enabled
) -> Checked[JsonObject]:
    """Answer one of the extension's ``METHODS``. Every skill fits on one
    page, so the server issues no cursor and rejects any it is given."""
    schema = {
        "skills/list": _LIST_PARAMS,
        "skills/get": _GET_PARAMS,
        "resources/directory/read": _READ_DIRECTORY_PARAMS,
    }[method]
    request = _decoded(schema, params)
    if isinstance(request, InvalidParams):
        return fail(request)
    if not catalog.present:
        # As a server that does not declare the extension.
        return fail(method_not_found(method))
    if request.get("cursor") is not None:
        return fail(InvalidParams("Unknown cursor"))
    if method == "skills/list":
        return catalog.list(enabled).map(lambda skills: {"skills": cast("Any", skills)})
    uri: str = request["uri"]
    if method == "skills/get":
        return catalog.get(uri, enabled).map(lambda skill: {"skill": cast("Any", skill)})
    return catalog.read_directory(uri, enabled).map(
        lambda children: {"resources": cast("Any", children)}
    )


__all__ = [
    "EXTENSION_ID",
    "METHODS",
    "DirectoryChild",
    "SkillCatalog",
    "SkillFile",
    "SkillFileInput",
    "SkillRegistration",
    "StaticSkill",
    "declare_extension",
    "make_static_skill",
    "method_not_found",
    "serve",
]
