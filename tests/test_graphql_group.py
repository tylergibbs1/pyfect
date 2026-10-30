"""GraphQLGroup classes: which operations a group (and a subclass) holds."""

from typing import TypedDict

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


class IssuesGroup(GraphQLGroup):
    repo_issues = RepoIssues
    issue_updated = IssueUpdated


class Count(GraphQLMiddleware): ...


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


def test_two_attributes_with_one_operation_name_are_rejected():
    class Twice(GraphQLGroup):
        first = IssueUpdated
        second = IssueUpdated.middleware(Count)

    try:
        client.make_test(Twice)
    except ValueError as error:
        assert "IssueUpdated" in str(error)
    else:
        raise AssertionError("expected a ValueError")
