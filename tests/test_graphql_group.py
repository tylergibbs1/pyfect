"""GraphQLGroup classes: which operations a group (and a subclass) holds."""

from typing import Never, TypedDict

import pytest

from pyfect import schema as S
from pyfect.graphql import GraphQLGroup, GraphQLMiddleware, client, query, subscription


class Login(TypedDict):
    login: str


class Viewer(TypedDict):
    viewer: Login


RepoIssues = query(
    "RepoIssues", document="query RepoIssues{viewer{login}}", result=S.Struct(Viewer)
)
IssueUpdated = subscription(
    "IssueUpdated", document="subscription IssueUpdated{viewer{login}}", result=S.Struct(Viewer)
)


class Count(GraphQLMiddleware): ...


class IssuesGroup(GraphQLGroup[Never, Count]):
    repo_issues = RepoIssues
    issue_updated = IssueUpdated


def test_a_subclass_overriding_an_operation_replaces_it():
    class Counted(IssuesGroup):
        issue_updated = IssueUpdated.middleware(Count)

    api = client.make_test(Counted)
    assert api.issue_updated.operation.middlewares == (Count,)
    assert isinstance(Counted.issue_updated.middlewares, tuple)


def test_a_subclass_keeps_the_operations_it_does_not_override():
    class Counted(IssuesGroup):
        issue_updated = IssueUpdated.middleware(Count)

    assert client.make_test(Counted).repo_issues.operation.name == "RepoIssues"


def test_two_attributes_with_one_operation_name_are_rejected_when_the_class_is_made():
    with pytest.raises(ValueError, match="IssueUpdated"):

        class Twice(GraphQLGroup[Never, Count]):  # pyright: ignore[reportUnusedClass]
            first = IssueUpdated
            second = IssueUpdated.middleware(Count)


class Auth(GraphQLMiddleware[Never, Never]): ...


class Authed(GraphQLGroup[Auth]):
    viewer = RepoIssues


def test_middleware_an_operation_runs_must_be_declared_for_make_to_require_it():
    # QA types 4: make() read the operation's middleware from the context
    # while its type left it out of R.
    with pytest.raises(TypeError, match=r"Undeclared's operations run middleware .*: Auth"):

        class Undeclared(GraphQLGroup):  # pyright: ignore[reportUnusedClass]
            viewer = RepoIssues.middleware(Auth)

    with pytest.raises(TypeError, match="does not declare: Auth"):

        class Taken(GraphQLGroup):  # pyright: ignore[reportUnusedClass]
            viewer = Authed.viewer

    class Declared(GraphQLGroup[Never, Auth]):
        viewer = RepoIssues.middleware(Auth)

    class Merged(GraphQLGroup[Never, Auth]):
        viewer = Authed.viewer

    assert client.make_test(Declared).viewer.operation.middlewares == (Auth,)
    assert client.make_test(Merged).viewer.operation.middlewares == (Auth,)


def test_a_subclass_of_a_group_keeps_its_group_middleware():
    class More(Authed):
        other = IssueUpdated

    # Read on the class, an operation carries the group's middleware.
    assert More.other.middlewares == (Auth,)
