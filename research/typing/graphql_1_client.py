"""Can a GraphQL group class type its client methods, with operation and
group middleware errors and services, and can ``make`` read the group's
middleware tags?

Run with ``uv run pyright -p research/typing research/typing/graphql_1_client.py``.

Findings (pyright 1.1.414):

G1. An operation is ``Operation[V, A, ME, MR]``: variables, result, the
    schemas' services and its middleware's errors and services, solved from
    the tag class through ``TagLike[Implementation[E, R], T]``.
G2. Read on a group instance, an operation is its client method; the group
    class's type argument (a union of middleware tags) adds their errors
    and services through a ``GraphQLGroup[GraphQLMiddleware[GE, GR]]``
    overload after a ``GraphQLGroup[Never]`` one.
G3. Read on the group class, an operation carries the group's middleware
    too, so another group can take it (Effect's ``GraphQLGroup.merge``).
G4. ``make(Group)`` solves both the instance type and the group's
    middleware tags from a classmethod returning ``GroupTypes[Self, GM]``.
G5. ``partial: Literal[True]`` overloads and a ``NoVariables`` self-type
    overload give the four call forms. The method is contravariant in its
    variables.
G6. ``pages`` / ``items`` read a connection through ``ReadOnly`` TypedDicts
    (``pageInfo``, ``nodes``), which a result TypedDict with more keys fits;
    ``items`` solves the node type from ``nodes``.

Negative finding: ``R | MR`` of two class TypeVars that are both ``Never``
is ``Unknown``, so an operation carries one services parameter (its
schemas' and its middleware's together).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import (
    Any,
    Generic,
    Literal,
    Never,
    NotRequired,
    Protocol,
    ReadOnly,
    Self,
    TypedDict,
    TypeVar,
    assert_type,
    overload,
)

from pyfect import Effect, Tag, TaggedError
from pyfect.context import TagLike

V = TypeVar("V")
V_contra = TypeVar("V_contra", contravariant=True)
A = TypeVar("A", covariant=True)
R = TypeVar("R", covariant=True)
ME = TypeVar("ME", covariant=True, default=Never)
MR = TypeVar("MR", covariant=True, default=Never)
GM = TypeVar("GM", covariant=True, default=Never)


class ClientError(TaggedError): ...


class Impl(Generic[ME, MR]):
    def run(self) -> Effect[None, ME, MR]: ...


class GraphQLMiddleware(Tag[Impl[ME, MR]], Generic[ME, MR]): ...


class NoVariables(TypedDict):
    pass


class PartialResult(Generic[A]): ...


class Method(Generic[V_contra, A, ME, MR]):
    @overload
    def __call__(
        self: Method[NoVariables, A, ME, MR],
        variables: None = None,
        /,
        *,
        partial: Literal[False] = False,
    ) -> Effect[A, ClientError | ME, MR]: ...
    @overload
    def __call__(
        self: Method[NoVariables, A, ME, MR],
        variables: None = None,
        /,
        *,
        partial: Literal[True],
    ) -> Effect[PartialResult[A], ClientError | ME, MR]: ...
    @overload
    def __call__(
        self, variables: V_contra, /, *, partial: Literal[False] = False
    ) -> Effect[A, ClientError | ME, MR]: ...
    @overload
    def __call__(
        self, variables: V_contra, /, *, partial: Literal[True]
    ) -> Effect[PartialResult[A], ClientError | ME, MR]: ...
    def __call__(self, variables: object = None, /, *, partial: bool = False) -> Any: ...


class GroupTypes(Generic[A, GM]): ...


class Group(Generic[GM]):
    @classmethod
    def __graphql_group__(cls) -> GroupTypes[Self, GM]: ...


class Operation(Generic[V, A, ME, MR]):
    @overload
    def __get__(self, instance: None, owner: type[Group[Never]], /) -> Self: ...
    @overload
    def __get__[GE, GR](
        self, instance: None, owner: type[Group[GraphQLMiddleware[GE, GR]]], /
    ) -> Operation[V, A, ME | GE, MR | GR]: ...
    @overload
    def __get__(self, instance: Group[Never], owner: type[object], /) -> Method[V, A, ME, MR]: ...
    @overload
    def __get__[GE, GR](
        self, instance: Group[GraphQLMiddleware[GE, GR]], owner: type[object], /
    ) -> Method[V, A, ME | GE, MR | GR]: ...
    def __get__(self, instance: object, owner: type[object], /) -> Any: ...

    def middleware[E2, R2, T](
        self, middleware: TagLike[Impl[E2, R2], T], /
    ) -> Operation[V, A, ME | E2, MR | R2]: ...


class Codec(Generic[A, R]): ...


def query[A1, RR = Never, V1 = NoVariables](
    name: str, *, result: Codec[A1, RR], variables: Codec[V1, RR] | None = None
) -> Operation[V1, A1, Never, RR]: ...


class GroupClass[G, T](Protocol):
    def __graphql_group__(self) -> GroupTypes[G, T]: ...


class Protocol_(Tag[int]): ...


def make[G, T](group: GroupClass[G, T]) -> Effect[G, Never, Protocol_ | T]: ...


# --- fixtures ----------------------------------------------------------------


class TokenExpired(TaggedError): ...


class RateLimited(TaggedError): ...


class CurrentUser(Tag[str]): ...


class Db(Tag[int]): ...


class Auth(GraphQLMiddleware[TokenExpired, CurrentUser]): ...


class Logging(GraphQLMiddleware[RateLimited, Db]): ...


class ViewerResult(TypedDict):
    login: str


class Vars(TypedDict):
    id: str


viewer_result: Codec[ViewerResult, Never] = Codec()
vars_codec: Codec[Vars, Never] = Codec()

Viewer = query("Viewer", result=viewer_result)
assert_type(Viewer, Operation[NoVariables, ViewerResult])
Issue = query("Issue", result=viewer_result, variables=vars_codec)
assert_type(Issue, Operation[Vars, ViewerResult])
assert_type(
    Viewer.middleware(Auth), Operation[NoVariables, ViewerResult, TokenExpired, CurrentUser]
)


class Plain(Group):
    viewer = Viewer
    authed = Viewer.middleware(Auth)
    issue = Issue


class Grouped(Group[Logging]):
    viewer = Viewer
    authed = Viewer.middleware(Auth)


class Two(Group[Auth | Logging]):
    viewer = Viewer


plain = Plain()
assert_type(plain.viewer, Method[NoVariables, ViewerResult, Never, Never])
assert_type(plain.viewer(), Effect[ViewerResult, ClientError])
assert_type(plain.viewer(partial=True), Effect[PartialResult[ViewerResult], ClientError])
assert_type(plain.issue({"id": "1"}), Effect[ViewerResult, ClientError])
assert_type(
    plain.issue({"id": "1"}, partial=True), Effect[PartialResult[ViewerResult], ClientError]
)
plain.issue()  # pyright: ignore[reportCallIssue]
assert_type(plain.authed(), Effect[ViewerResult, ClientError | TokenExpired, CurrentUser])
assert_type(Grouped().viewer(), Effect[ViewerResult, ClientError | RateLimited, Db])
assert_type(
    Grouped().authed(),
    Effect[ViewerResult, ClientError | TokenExpired | RateLimited, CurrentUser | Db],
)
assert_type(
    Two().viewer(), Effect[ViewerResult, ClientError | TokenExpired | RateLimited, CurrentUser | Db]
)

# G3: through the class, the group's middleware comes along.
assert_type(Plain.viewer, Operation[NoVariables, ViewerResult])
assert_type(Grouped.viewer, Operation[NoVariables, ViewerResult, RateLimited, Db])


class Merged(Group):
    viewer = Grouped.viewer


assert_type(Merged().viewer(), Effect[ViewerResult, ClientError | RateLimited, Db])

# G4
assert_type(make(Plain), Effect[Plain, Never, Protocol_])
assert_type(make(Grouped), Effect[Grouped, Never, Protocol_ | Logging])
assert_type(make(Two), Effect[Two, Never, Protocol_ | Auth | Logging])


# --- G6: pages / items read a connection through ReadOnly TypedDicts ---------


C = TypeVar("C")
N = TypeVar("N")


class PageInfo(TypedDict):
    hasNextPage: ReadOnly[bool]
    endCursor: ReadOnly[str | None]


class Connection(TypedDict):
    pageInfo: ReadOnly[PageInfo]


class NodesConnection(Connection, Generic[N]):
    nodes: ReadOnly[Sequence[N] | None]


def pages[V1, A1, E1, R1, C1: Connection](
    method: Method[V1, A1, E1, R1], *, variables: V1, connection: Callable[[A1], C1 | None]
) -> Effect[Sequence[C1], ClientError | E1, R1]: ...


def items[V1, A1, E1, R1, N1](
    method: Method[V1, A1, E1, R1],
    *,
    variables: V1,
    connection: Callable[[A1], NodesConnection[N1] | None],
) -> Effect[Sequence[N1], ClientError | E1, R1]: ...


class IssuePageInfo(TypedDict):
    hasNextPage: bool
    endCursor: str | None


class Node(TypedDict):
    number: int


class Issues(TypedDict):
    pageInfo: IssuePageInfo
    nodes: list[Node | None] | None


class Repo(TypedDict):
    issues: Issues | None


class RepoIssues(TypedDict):
    repository: Repo | None


class PagedVars(TypedDict):
    owner: str
    after: NotRequired[str | None]


paged: Method[PagedVars, RepoIssues, Never, Never] = Method()


def issues_of(r: RepoIssues) -> Issues | None:
    return None if r["repository"] is None else r["repository"]["issues"]


assert_type(
    pages(paged, variables={"owner": "x"}, connection=issues_of),
    Effect[Sequence[Issues], ClientError],
)
assert_type(
    items(paged, variables={"owner": "x"}, connection=issues_of),
    Effect[Sequence[Node | None], ClientError],
)
