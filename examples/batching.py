"""Request batching: the N+1 query problem collapsed into one batched query.

Rendering a feed needs every post's author. Written naively, that is one
query for the posts plus one per post. Here each author lookup is a
request, and the lookups made concurrently in the same tick go to the
database as one ``WHERE id IN (...)`` query. A cached resolver then
answers repeated lookups without querying at all.

Run with: uv run examples/batching.py
"""

from collections.abc import Sequence
from dataclasses import dataclass

import pyfect as fx
from pyfect.batching import Entry

# --- a pretend database that logs its queries ---------------------------------------

AUTHORS = {1: "Ada", 2: "Grace", 3: "Linus"}
POSTS = [(10, 1), (11, 2), (12, 1), (13, 3), (14, 2), (15, 4)]  # (post id, author id)


def query(sql: str) -> None:
    print(f"db: {sql}")


# --- the request and its resolver ----------------------------------------------------


@dataclass
class AuthorNotFound(fx.TaggedError):
    author_id: int


@dataclass(frozen=True)
class GetAuthor(fx.Request[str, AuthorNotFound]):
    """Look up one author's name. Frozen, so equal requests compare equal."""

    id: int


def authors_by_id(entries: Sequence[Entry[GetAuthor]]) -> fx.Effect[None]:
    """One query for a whole batch, then one answer per request."""

    def run() -> None:
        ids = sorted({entry.request.id for entry in entries})
        query(f"SELECT id, name FROM authors WHERE id IN ({', '.join(map(str, ids))})")
        for entry in entries:
            name = AUTHORS.get(entry.request.id)
            if name is None:
                entry.complete_unsafe(fx.exit.fail(AuthorNotFound(entry.request.id)))
            else:
                entry.complete_unsafe(fx.Success(name))

    return fx.sync(run)


Authors = fx.RequestResolver(authors_by_id)


def author_of(post: tuple[int, int], resolver: fx.RequestResolver[GetAuthor]):
    post_id, author_id = post
    return (
        fx.request(GetAuthor(author_id), resolver)
        .map(lambda name: f"post {post_id} by {name}")
        .pipe(
            fx.catch_tag(AuthorNotFound, lambda e: fx.succeed(f"post {post_id} by #{e.author_id}?"))
        )
    )


def feed(resolver: fx.RequestResolver[GetAuthor]) -> fx.Effect[list[str]]:
    """Every post with its author: N lookups, made concurrently."""
    return fx.for_each(POSTS, lambda post: author_of(post, resolver), concurrency="unbounded")


@fx.gen
def program():
    query("SELECT id, author_id FROM posts")
    for line in (yield from feed(Authors)):
        print(line)

    # A cached resolver remembers answers: the second feed sends no query.
    cached = yield from Authors.with_cache(capacity=100)
    yield from feed(cached)
    lines = yield from feed(cached)
    print(f"cached feed: {len(lines)} posts")


if __name__ == "__main__":
    fx.run_sync(program)
