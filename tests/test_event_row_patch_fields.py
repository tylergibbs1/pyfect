"""An event row's patch writes only its non-key fields (dogfood quill #4): a key field or a
field the row does not have is an ``EventRowPatchError`` when the patch is made, not an
entry written and synced as a no-op. Effect rejects both at compile time
(``PatchFields<Fields, Key>``); ``patch_fields`` lets pyright do the same here."""

from typing import TypedDict

import pytest

from pyfect import schema as S
from pyfect.eventlog import event_row


class NoteRow(TypedDict):
    id: str
    title: str
    pinned: bool


class NotePatch(TypedDict, total=False):
    title: str
    pinned: bool


Note = event_row.make(
    "note", key="id", schema=S.Struct(NoteRow), key_type=str, patch_fields=NotePatch
)


def test_a_patch_of_non_key_fields_is_written() -> None:
    assert Note.patch("n1", {"title": "x"}).payload == {
        "_tag": "patch",
        "key": "n1",
        "fields": {"title": "x"},
    }


@pytest.mark.parametrize("fields", [{"titel": "x"}, {"id": "n2"}, {"title": "x", "id": "n2"}])
def test_a_patch_of_a_key_or_unknown_field_is_rejected_when_made(fields: dict[str, object]) -> None:
    untyped = event_row.make("note", key="id", schema=S.Struct(NoteRow))
    with pytest.raises(event_row.EventRowPatchError) as raised:
        untyped.patch("n1", fields)
    assert raised.value.fields == tuple(
        name for name in fields if name not in NotePatch.__annotations__
    )


def test_patch_fields_must_name_exactly_the_non_key_fields() -> None:
    class Partial(TypedDict, total=False):
        title: str

    class WithKey(TypedDict, total=False):
        id: str
        title: str
        pinned: bool

    for wrong in (Partial, WithKey):
        with pytest.raises(ValueError, match="non-key fields"):
            event_row.make("note", key="id", schema=S.Struct(NoteRow), patch_fields=wrong)
