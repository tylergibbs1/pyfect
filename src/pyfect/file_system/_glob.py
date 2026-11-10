"""``FileSystem.glob`` derived from ``read_directory_entries``, ``stat`` and
``read_link`` (Effect's ``internal/glob.ts``, file system walk).

Results are ``/``-separated paths relative to ``root`` (absolute for an
absolute pattern), depth first, each directory's entries sorted by name.
``**`` does not traverse symbolic links to directories; a link named by
another segment is followed. Named directories (the root and those reached
only through leading literal segments) must be readable; unreadable
directories reached through wildcards are skipped, and missing paths give
nothing. Up to 16 directories are read at once across the walk."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyfect import exit as exit_
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._js import js_sort_key
from pyfect.cause import Cause
from pyfect.deferred import Deferred
from pyfect.effect import gen, succeed, suspend, sync
from pyfect.file_system._model import DirectoryEntry, FileInfo, FileType
from pyfect.glob._compile import (
    Compiled,
    End,
    compile,
    is_absolute,
    is_root,
)
from pyfect.glob._compile import (
    Literal as LiteralNode,
)
from pyfect.glob._match import (
    States,
    accepts,
    can_descend,
    needs_directory,
    step,
    union,
)
from pyfect.platform_error import (
    BadResource,
    NotFound,
    PermissionDenied,
    PlatformError,
    Unknown,
)

if TYPE_CHECKING:
    from pyfect.file_system._service import FileSystemService

_CONCURRENCY = 16


def _join(parent: str, name: str) -> str:
    if parent == "":
        return "/" if name == "" else name
    return parent + name if parent.endswith("/") else f"{parent}/{name}"


def _is_missing(error: PlatformError) -> bool:
    return isinstance(error.reason, NotFound | BadResource)


def _is_ignorable(error: PlatformError) -> bool:
    return _is_missing(error) or isinstance(error.reason, PermissionDenied)


def _is_not_link(error: PlatformError) -> bool:
    # Node reports `readlink` of a path that is no link (EINVAL) as "Unknown"
    return _is_ignorable(error) or isinstance(error.reason, Unknown)


def _is_not_found(error: PlatformError) -> bool:
    return isinstance(error.reason, NotFound)


def _type_of(info: FileInfo) -> FileType | None:
    return info.type


def _symbolic_link(_: str) -> FileType | None:
    return "SymbolicLink"


def _no_type(_: PlatformError) -> Effect[FileType | None]:
    return succeed(None)


def _is_unlisted(value: str) -> bool:
    """Listings never hold ``.``, ``..`` or the root of an absolute pattern."""
    return value in (".", "..") or is_root(value)


@dataclass(frozen=True, slots=True)
class _Child:
    relative: str
    accepted: bool
    excluded: States
    next: States | None


@dataclass(frozen=True, slots=True)
class _Listing:
    entries: list[DirectoryEntry]
    named: bool


def glob(
    fs: FileSystemService,
    pattern: str,
    *,
    root: str | None,
    exclude: Iterable[str],
    dot: bool,
) -> Effect[list[str], PlatformError]:
    excludes = tuple(exclude)
    return suspend(lambda: _Walk(fs, compile([pattern], dot), root or "", excludes).run())


class _Walk:
    """One run of a glob: the compiled patterns and the state the forked
    directory walks share."""

    def __init__(
        self, fs: FileSystemService, compiled: Compiled, root: str, exclude: tuple[str, ...]
    ) -> None:
        self.fs = fs
        self.compiled = compiled
        self.root = root
        self.excludes = compile(exclude, True)
        self.exclude_needs_directory = any(
            isinstance(node, End) and node.directory_only for node in self.excludes.nodes
        )
        self.slots = _CONCURRENCY
        self.finishing = False
        self.failed = Deferred[Any, PlatformError]()

    def run(self) -> Effect[list[str], PlatformError]:
        if not self.compiled.initial:
            return succeed([])
        walk = self.directory("", self.compiled.initial, self.excludes.initial, True)
        # The losing walk is interrupted along with every fiber it forked
        return walk.ensuring(sync(self._finish)).race_first(self.failed.wait())

    def _finish(self) -> None:
        self.finishing = True

    def fs_path(self, relative: str) -> str:
        if is_absolute(relative):
            return relative
        if relative == "":
            return "." if self.root == "" else self.root
        return _join(self.root, relative)

    def probe(
        self, parent: str, name: str, named: bool
    ) -> Effect[DirectoryEntry | None, PlatformError]:
        """Keeps broken links, so literal probes agree with listings."""
        path = self.fs_path(_join(parent, name))
        fs = self.fs

        def read_link(_: PlatformError) -> Effect[FileType | None, PlatformError]:
            return fs.read_link(path).map(_symbolic_link).catch_if(_is_not_link, _no_type)

        found = fs.stat(path).map(_type_of).catch_if(_is_not_found, read_link)
        return found.catch_if(_is_missing if named else _is_ignorable, lambda _: succeed(None)).map(
            lambda type: None if type is None else DirectoryEntry(name, type)
        )

    def entries(
        self, relative: str, states: States, named: bool
    ) -> Effect[_Listing, PlatformError]:
        """Probes leading literals without needing permission to list their parent."""
        literals: dict[str, None] = {}
        listed = not named
        for state in states:
            node = self.compiled.nodes[state]
            if isinstance(node, LiteralNode):
                literals[node.value] = None
            elif not isinstance(node, End):
                listed = True
        probed = [name for name in literals if _is_unlisted(name)] if listed else list(literals)
        empty: list[DirectoryEntry] = []
        listing: Effect[list[DirectoryEntry], PlatformError] = (
            self.fs.read_directory_entries(self.fs_path(relative))
            .map(list)
            .catch_if(_is_missing if named else _is_ignorable, lambda _: succeed(empty))
            if listed
            else succeed(empty)
        )

        def combine(found: list[DirectoryEntry], probes: list[DirectoryEntry | None]) -> _Listing:
            merged = [*found, *(entry for entry in probes if entry is not None)]
            merged.sort(key=lambda entry: js_sort_key(entry.name))
            return _Listing(merged, named and not listed)

        return listing.zip_with(
            for_each(probed, lambda name: self.probe(relative, name, named), concurrency=16),
            combine,
        )

    def visit(
        self, entry: DirectoryEntry, parent: str, states: States, excluded: States
    ) -> _Child | Effect[_Child | None, PlatformError] | None:
        """Synchronous unless the entry's type must come from ``stat`` /
        ``read_link``."""
        compiled = self.compiled
        result = step(compiled, states, entry.name)
        following = union(result)
        if not following:
            return None
        relative = _join(parent, entry.name)
        next_excluded = union(step(self.excludes, excluded, entry.name))
        descend = can_descend(compiled, following)

        def child(is_directory: bool, link: bool) -> _Child | None:
            accepted = accepts(compiled, following, is_directory)
            if (not accepted and (not is_directory or not descend)) or accepts(
                self.excludes, next_excluded, is_directory
            ):
                return None
            states_after: States | None
            if not is_directory or not descend:
                states_after = None
            elif not link or not result.globstar:
                states_after = following
            elif can_descend(compiled, result.explicit):
                # Follow symbolic links only through explicit segments, not `**`.
                states_after = result.explicit
            else:
                states_after = None
            return _Child(relative, accepted, next_excluded, states_after)

        if (
            not descend
            and not needs_directory(compiled, following)
            and not self.exclude_needs_directory
        ):
            return child(False, False)
        if entry.type not in ("Unknown", "SymbolicLink"):
            return child(entry.type == "Directory", False)
        path = self.fs_path(relative)
        is_link = entry.type == "SymbolicLink"

        def resolve(is_directory: bool) -> Effect[_Child | None, PlatformError]:
            resolved = child(is_directory, is_link)
            if is_link or resolved is None or resolved.next is None or not result.globstar:
                return succeed(resolved)
            return (
                self.fs.read_link(path)
                .map(lambda _: child(is_directory, True))
                .catch_if(_is_not_link, lambda _: succeed(resolved))
            )

        is_dir: Effect[bool, PlatformError] = (
            self.fs.stat(path)
            .map(lambda info: info.type == "Directory")
            .catch_if(_is_ignorable, lambda _: succeed(False))
        )
        return is_dir.flat_map(resolve)

    def fork(self, walk: Effect[list[str], PlatformError]) -> Effect[Any]:
        """Walk a subdirectory in a child fiber; its failure ends the whole
        walk through ``failed``, even while its parent walks another
        subdirectory inline. Once the root walk is finishing, forked walks
        only exit because it interrupts them."""

        def report(cause: Cause[PlatformError]) -> Effect[None]:
            def done() -> None:
                if not self.finishing:
                    self.failed.done_unsafe(exit_.fail_cause(cause))

            return sync(done)

        def free() -> None:
            self.slots += 1

        return walk.on_error(report).ensuring(sync(free)).fork()

    def directory(
        self, relative: str, states: States, excluded: States, named: bool
    ) -> Effect[list[str], PlatformError]:
        def body() -> Generator[Effect[Any, PlatformError], Any, list[str]]:
            listing: _Listing = yield from self.entries(relative, states, named)
            children: list[_Child | None] = []
            pending: list[Effect[None, PlatformError]] = []
            for entry in listing.entries:
                visited = self.visit(entry, relative, states, excluded)
                if isinstance(visited, Effect):
                    children.append(None)
                    pending.append(visited.map(_store(children, len(children) - 1)))
                else:
                    children.append(visited)
            if pending:
                yield from for_each(pending, _identity, concurrency=16)
            subtrees: list[Effect[list[str], PlatformError]] = []
            for child in children:
                if child is not None and child.next is not None:
                    walk = self.directory(child.relative, child.next, child.excluded, listing.named)
                    if self.slots > 0:
                        self.slots -= 1
                        fiber = yield from self.fork(walk)
                        subtrees.append(fiber.join())
                    else:
                        subtrees.append(succeed((yield from walk)))
            # Splice the subtrees back in listing order
            out: list[str] = []
            index = 0
            for child in children:
                if child is None:
                    continue
                if child.accepted:
                    out.append(child.relative)
                if child.next is not None:
                    out.extend((yield from subtrees[index]))
                    index += 1
            return out

        return gen(body)


def _identity[A](effect: A) -> A:
    return effect


def _store(children: list[_Child | None], index: int) -> Callable[[_Child | None], None]:
    def store(child: _Child | None) -> None:
        children[index] = child

    return store
