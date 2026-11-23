"""Ports of Effect's ``test/ai/Skill.test.ts``: a standalone Agent Skill value.

Each test's docstring is the Effect test title. Effect's ``Uint8Array`` files
are ``bytes``; its ``1n`` (a bigint, not JSON) frontmatter value is a
``set``; ``Schema.fromJsonString(Schema.toCodecJson(Skill))`` is
``S.from_json_string(S.to_codec_json(skill.Skill))``.
"""

from __future__ import annotations

from typing import Any

import pytest

from pyfect import schema as S
from pyfect import testing
from pyfect.ai import skill
from pyfect.errors import IllegalArgumentError

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def test_validates_frontmatter_and_file_paths_on_construction():
    """validates frontmatter and file paths on construction"""
    refunds = skill.make(
        frontmatter={"name": "refunds", "description": "Process customer refunds"},
        instructions="Read references/policy.md before issuing a refund.",
    )
    assert isinstance(refunds, skill.Skill)
    assert refunds.files == {}

    with pytest.raises(S.SchemaError):
        skill.make(
            frontmatter={"name": "Bad_Name", "description": "Process customer refunds"},
            instructions="",
        )

    not_json: Any = {1}
    with pytest.raises(S.SchemaError):
        skill.make(
            frontmatter={
                "name": "refunds",
                "description": "Process customer refunds",
                "revision": not_json,
            },
            instructions="",
        )

    for path in ("../secret.txt", "C:/notes.txt", "SKILL.md"):
        with pytest.raises(S.SchemaError):
            skill.make(
                frontmatter={"name": "refunds", "description": "Process customer refunds"},
                instructions="",
                files={path: "secret"},
            )


@testing.effect
def test_round_trips_through_to_files_and_from_files_and_rejects_invalid_file_bundles():
    """round-trips through toFiles and fromFiles, and rejects invalid file bundles"""
    refunds = skill.make(
        frontmatter={
            "name": "refunds",
            "description": "yes: it's #1",
            "metadata": {"version": "1.0"},
            "#note": "retain",
        },
        instructions="Read references/policy.md before issuing a refund.",
        files={
            "references/policy.md": "Refunds over $100 require approval.",
            "assets/logo.png": PNG,
            "__proto__": "proto-file",
        },
    )

    round_tripped = yield from skill.from_files(skill.to_files(refunds))
    assert round_tripped == refunds
    assert "__proto__" in round_tripped.files

    missing_skill_md = yield from skill.from_files({"references/policy.md": "orphan"}).flip()
    assert isinstance(missing_skill_md, IllegalArgumentError)

    bad_frontmatter = yield from skill.from_files(
        {"SKILL.md": "---\nname: Bad_Name\ndescription: bad\n---\n\nBody"}
    ).flip()
    assert isinstance(bad_frontmatter, IllegalArgumentError)


@testing.effect
def test_round_trips_text_and_binary_files_through_json():
    """round-trips text and binary files through JSON"""
    refunds = skill.make(
        frontmatter={"name": "refunds", "description": "Process customer refunds"},
        instructions="Read references/policy.md before issuing a refund.",
        files={
            "references/policy.md": "Refunds over $100 require approval.",
            "assets/logo.png": PNG,
        },
    )

    codec = S.from_json_string(S.to_codec_json(skill.Skill))
    encoded = yield from S.encode_effect(codec)(refunds)
    decoded = yield from S.decode_unknown_effect(codec)(encoded)

    assert isinstance(decoded, skill.Skill)
    assert isinstance(decoded.files["assets/logo.png"], bytes)
    assert decoded == refunds


# --- cases Effect's tests leave open --------------------------------------------------


def test_to_files_writes_skill_md_first_with_json_encoded_frontmatter():
    refunds = skill.make(
        frontmatter={"name": "refunds", "description": "Process refunds"},
        instructions="Body\n",
        files={"references/policy.md": "Policy"},
    )
    assert skill.to_files(refunds) == {
        "SKILL.md": '---\n"name": "refunds"\n"description": "Process refunds"\n---\n\nBody\n',
        "references/policy.md": "Policy",
    }


@testing.effect
def test_from_files_reads_a_hand_written_skill_md_from_bytes():
    parsed = yield from skill.from_files(
        {"SKILL.md": b"\xef\xbb\xbf---\r\nname: refunds\r\ndescription: Refund\r\n---\r\n\r\nBody"}
    )
    assert parsed.frontmatter == {"name": "refunds", "description": "Refund"}
    assert parsed.instructions == "Body"


@testing.effect
def test_from_files_rejects_a_skill_md_that_is_not_utf_8_or_has_no_frontmatter():
    not_utf8 = yield from skill.from_files({"SKILL.md": b"\xff"}).flip()
    assert str(not_utf8) == "SKILL.md is not valid UTF-8"
    no_frontmatter = yield from skill.from_files({"SKILL.md": "Body"}).flip()
    assert str(no_frontmatter) == "SKILL.md is missing valid YAML frontmatter"
    unsafe = yield from skill.from_files(
        {"SKILL.md": skill.to_files(_refunds())["SKILL.md"], "a//b": "x"}
    ).flip()
    assert 'Invalid skill file path "a//b"' in str(unsafe)


def _refunds() -> skill.Skill:
    return skill.make(
        frontmatter={"name": "refunds", "description": "Process refunds"}, instructions=""
    )


def test_the_json_codec_writes_bytes_as_base64_objects_and_text_as_strings():
    refunds = skill.make(
        frontmatter={"name": "refunds", "description": "Process refunds"},
        instructions="",
        files={"logo.png": PNG, "policy.md": "Policy"},
    )
    encoded = S.encode_sync(S.to_codec_json(skill.Skill))(refunds)
    assert encoded == {
        "frontmatter": {"name": "refunds", "description": "Process refunds"},
        "instructions": "",
        "files": {"logo.png": {"base64": "iVBORw0KGgo="}, "policy.md": "Policy"},
    }
