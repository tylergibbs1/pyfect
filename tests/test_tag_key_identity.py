"""A tag's key is its identity, as in Effect (whose ``Context`` maps key strings to services):
two tag classes with the same key are one service, and tags with different keys stay apart
whatever their shape. A second declaration taking a key another declaration holds warns, naming
both, since that is how two unrelated tags would silently merge."""

import warnings

import pytest

import pyfect as fx
from pyfect.context import Context, DuplicateTagKeyWarning, Reference, Tag
from pyfect.http_api import HttpApiGroup


class Primary(Tag[str], key="test/tag_key_identity/Database"):
    pass


with warnings.catch_warnings():
    warnings.simplefilter("ignore", DuplicateTagKeyWarning)

    class SameDatabase(Tag[str], key="test/tag_key_identity/Database"):
        pass


class Replica(Tag[str], key="test/tag_key_identity/Replica"):
    pass


def test_two_tags_with_one_key_are_one_service():
    ctx = Context.make(Primary, "db")
    assert ctx.get_unsafe(SameDatabase) == "db"
    assert ctx.add(SameDatabase, "other").get_unsafe(Primary) == "other"
    assert len(ctx.add(SameDatabase, "other").tags()) == 1
    # The types can't see two classes share a key: SameDatabase stays required.
    provided = SameDatabase().pipe(fx.provide_service(Primary, "db"))
    assert fx.run_sync(provided) == "db"  # pyright: ignore[reportArgumentType]


def test_tags_with_different_keys_stay_apart():
    ctx = Context.make(Primary, "primary").add(Replica, "replica")
    assert (ctx.get_unsafe(Primary), ctx.get_unsafe(Replica)) == ("primary", "replica")
    assert ctx.pipe(Context.omit(SameDatabase)).tags() == (Replica,)
    picked = ctx.pipe(Context.pick(SameDatabase))  # pyright: ignore[reportArgumentType]
    assert picked.get_unsafe(Primary) == "primary"


def test_a_second_declaration_with_a_taken_key_warns_naming_both():
    with pytest.warns(DuplicateTagKeyWarning) as caught:

        class Clash(Tag[int], key="test/tag_key_identity/Replica"):  # pyright: ignore[reportUnusedClass]
            pass

    message = str(caught[0].message)
    assert "test_a_second_declaration_with_a_taken_key_warns_naming_both.<locals>.Clash" in message
    assert "tests.test_tag_key_identity.Replica" in message or "Replica" in message
    assert "give one a different key" in message


def test_declaring_the_same_tag_again_does_not_warn():
    def declare() -> type[Tag[int]]:
        class Local(Tag[int]):
            pass

        return Local

    with warnings.catch_warnings():
        warnings.simplefilter("error", DuplicateTagKeyWarning)
        first, second = declare(), declare()
    assert first is not second
    assert Context.make(first, 1).get_unsafe(second) == 1


def test_references_with_one_key_share_the_service_and_the_default():
    class Level(Reference[int], key="test/tag_key_identity/Level"):
        @classmethod
        def default(cls) -> int:
            return 1

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DuplicateTagKeyWarning)

        class SameLevel(Reference[int], key="test/tag_key_identity/Level"):
            @classmethod
            def default(cls) -> int:
                return 2

    assert Context.empty().get_unsafe(SameLevel) == Context.empty().get_unsafe(Level)
    assert Context.make(Level, 5).get_unsafe(SameLevel) == 5


def test_http_api_groups_sharing_an_identifier_are_one_service_without_a_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DuplicateTagKeyWarning)

        class First(HttpApiGroup, identifier="tag_key_identity_users"):
            pass

        class Second(HttpApiGroup, identifier="tag_key_identity_users"):
            pass

    assert Second.__tag_identity__ is First
