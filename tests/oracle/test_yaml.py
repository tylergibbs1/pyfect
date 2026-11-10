"""Ports of Effect's ``encoding/Yaml.test.ts``. Each test's docstring is the
Effect test title; an ``it.each`` table is a parametrized test."""

from __future__ import annotations

import re
from typing import Any

import pytest

from pyfect.encoding import yaml


def test_parses_nested_block_and_flow_collections():
    """parses nested block and flow collections"""
    source = """
name: effect
enabled: true
ports: [3000, 3001]
database:
  host: localhost
  credentials:
    - user: root
      roles: [admin, writer]
    - user: guest
      roles: []
"""
    assert yaml.parse(source) == {
        "name": "effect",
        "enabled": True,
        "ports": [3000, 3001],
        "database": {
            "host": "localhost",
            "credentials": [
                {"user": "root", "roles": ["admin", "writer"]},
                {"user": "guest", "roles": []},
            ],
        },
    }


def test_parses_quoted_and_block_scalars():
    """parses quoted and block scalars"""
    source = """
quoted: "line\\nvalue"
literal: |
  first
  second
folded: >-
  first
  second
"""
    assert yaml.parse(source) == {
        "quoted": "line\nvalue",
        "literal": "first\nsecond\n",
        "folded": "first second",
    }


def test_preserves_paragraph_and_indentation_breaks_in_folded_block_scalars():
    """preserves paragraph and indentation breaks in folded block scalars"""
    source = """
paragraph: >-
  first

  second
indented: >-
  first
    second
  third
"""
    assert yaml.parse(source) == {
        "paragraph": "first\nsecond",
        "indented": "first\n  second\nthird",
    }


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        (
            "leading blanks before a more-indented first line",
            "message: >-2\n\n    first\n  second\n",
            "\n  first\nsecond",
        ),
        (
            "keep chomping after a more-indented final line",
            "message: >+2\n  first\n    second\n",
            "first\n  second\n",
        ),
        (
            "multiple blank paragraph lines",
            "message: >-\n  first\n\n\n  second\n",
            "first\n\nsecond",
        ),
        ("literal tab content", "message: |\n  all:\n  \tcc\n", "all:\n\tcc\n"),
        ("folded tab-led content", "message: >\n  a\n  \tb\n  c\n", "a\n\tb\nc\n"),
        ("whitespace-only content", "message: |\n  a\n    \n  b\n", "a\n  \nb\n"),
        ("explicit-indicator leading whitespace", "message: |1\n   \n  x\n", "  \n x\n"),
    ],
)
def test_preserves(name: str, source: str, expected: str):
    """preserves %s"""
    assert yaml.parse(source) == {"message": expected}, name


_SIBLING_CHOMPING = [
    ("strip", "-", "  text\n\n\n", "text"),
    ("clip", "", "  text\n\n\n", "text\n"),
    ("keep", "+", "  text\n\n\n", "text\n\n\n"),
    ("keep without trailing empty lines", "+", "  text\n", "text\n"),
    ("empty clip", "", "", ""),
    ("empty keep", "+", "", ""),
    ("keep with only empty lines", "+", "\n\n", "\n\n"),
]


@pytest.mark.parametrize("style", ["|", ">"])
@pytest.mark.parametrize(("name", "chomp", "content", "expected"), _SIBLING_CHOMPING)
def test_block_scalar_chomping_applies_before_a_sibling_key(
    style: str, name: str, chomp: str, content: str, expected: str
):
    """block scalar chomping (%s) applies %s before a sibling key"""
    assert yaml.parse(f"message: {style}{chomp}\n{content}next: 1\n") == {
        "message": expected,
        "next": 1,
    }, name


@pytest.mark.parametrize("style", ["|", ">"])
@pytest.mark.parametrize(
    ("name", "chomp", "content", "expected"),
    [
        ("clip without a final line break", "", "  text", "text"),
        ("keep without a final line break", "+", "  text", "text"),
        ("keep with trailing empty lines", "+", "  text\n\n\n", "text\n\n\n"),
    ],
)
def test_block_scalar_chomping_applies_at_end_of_input(
    style: str, name: str, chomp: str, content: str, expected: str
):
    """block scalar chomping (%s) applies %s at end-of-input"""
    assert yaml.parse(f"message: {style}{chomp}\n{content}") == {"message": expected}, name


def test_parses_yaml_1_2_2_example_8_6_empty_scalar_chomping():
    """parses YAML 1.2.2 example 8.6 (empty scalar chomping)"""
    assert yaml.parse("strip: >-\n\nclip: >\n\nkeep: |+\n\n") == {
        "strip": "",
        "clip": "",
        "keep": "\n",
    }


def test_preserves_kept_trailing_lines_in_block_sequence_entries():
    """preserves kept trailing lines in block sequence entries"""
    assert yaml.parse("- |+\n  first\n\n- second\n") == ["first\n\n", "second"]


@pytest.mark.parametrize(
    ("indicator", "content", "expected"),
    [
        ("|", "    first\n    second\n", "first\nsecond\n"),
        (">-", "\n    first\n    second\n\n", "\nfirst second"),
        ("|2+", "    # text\n\n", "  # text\n\n"),
    ],
)
def test_ends_scalars_before_less_indented_comments(indicator: str, content: str, expected: str):
    """ends %s scalars before less-indented comments"""
    assert yaml.parse(f"message: {indicator}\n{content} # outside\nnext: 1\n") == {
        "message": expected,
        "next": 1,
    }


def test_rejects_less_indented_block_scalar_content():
    """rejects less-indented block scalar content"""
    with pytest.raises(ValueError):
        yaml.parse("message: |\n    first\n  second\nnext: 1\n")


def test_resolves_aliases():
    """resolves aliases"""
    source = """
defaults: &defaults
  host: localhost
  port: 5432
development:
  settings: *defaults
"""
    assert yaml.parse(source) == {
        "defaults": {"host": "localhost", "port": 5432},
        "development": {"settings": {"host": "localhost", "port": 5432}},
    }


def test_rejects_invalid_indentation():
    """rejects invalid indentation"""
    with pytest.raises(ValueError):
        yaml.parse("root:\n   child: true\n  sibling: false\n")


def test_allows_tabs_on_comment_and_blank_lines_outside_scalars():
    """allows tabs on comment and blank lines outside scalars"""
    assert yaml.parse("a: 1\n\t# comment\n\t\nb: 2\n") == {"a": 1, "b": 2}


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("structural indentation", "root:\n\tchild: true\n"),
        ("below block content indentation", "text: |\n  x\n\t\nnext: 1\n"),
        ("plain continuation", "text: a\n\t\n  b\n"),
        ("single-quoted continuation", "text: 'a\n\tb'\n"),
        ("double-quoted continuation", 'text: "a\n\tb"\n'),
    ],
)
def test_rejects_tabs_in(name: str, source: str):
    """rejects tabs in %s"""
    with pytest.raises(ValueError, match="Tabs cannot be used for YAML indentation"):
        yaml.parse(source)


def test_rejects_leading_empty_lines_more_indented_than_the_first_block_content_line():
    """rejects leading empty lines more indented than the first block content line"""
    with pytest.raises(ValueError):
        yaml.parse("text: |\n    \n  \tx\n")


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        (
            "top-level mapping value",
            "allowed-tools:\n- Read\n- Bash\n",
            {"allowed-tools": ["Read", "Bash"]},
        ),
        (
            "nested mapping value",
            "metadata:\n  tools:\n  - Read\n",
            {"metadata": {"tools": ["Read"]}},
        ),
        (
            "multiple sequences and sibling keys",
            "tools:\n- Read\n- Bash\nroles:\n- admin\nenabled: true\n",
            {"tools": ["Read", "Bash"], "roles": ["admin"], "enabled": True},
        ),
        (
            "comments and blank lines before and between items",
            "tools: # key comment\n# before sequence\n\n- Read # item comment\n"
            "  # between items\n\n- Bash\n",
            {"tools": ["Read", "Bash"]},
        ),
        (
            "nested mapping items and their indentless sequences",
            "steps:\n- name: deploy\n  tools:\n  - Read\n  - Bash\n  enabled: true\n"
            "- name: verify\n",
            {
                "steps": [
                    {"name": "deploy", "tools": ["Read", "Bash"], "enabled": True},
                    {"name": "verify"},
                ]
            },
        ),
        (
            "nested sequences ending at mapping boundaries",
            "metadata:\n  tools:\n  - Read\n  roles:\n  - admin\n  enabled: true\nname: deploy\n",
            {
                "metadata": {"tools": ["Read"], "roles": ["admin"], "enabled": True},
                "name": "deploy",
            },
        ),
        (
            "multiline descriptions alongside sequences",
            "description: Deploy the service\n  and verify it.\ntools:\n- Read\nmetadata:\n"
            "  description: 'Check\n    the logs'\n  tools:\n  - Bash\n",
            {
                "description": "Deploy the service and verify it.",
                "tools": ["Read"],
                "metadata": {"description": "Check the logs", "tools": ["Bash"]},
            },
        ),
    ],
)
def test_indentless_sequences_parses(name: str, source: str, expected: object):
    """indentless sequences parses $name"""
    assert yaml.parse(source) == expected, name


_FLOW_SCALARS = [
    (
        "plain scalar starting below the key",
        "description:\n  Deploy the service\n  and verify it.\n",
        "Deploy the service and verify it.",
    ),
    (
        "plain scalar starting on the key line",
        "description: Deploy the service\n  and verify it.\n",
        "Deploy the service and verify it.",
    ),
    (
        "varying continuation indentation",
        "description:\n    Deploy\n  the service\n      and verify it.\n",
        "Deploy the service and verify it.",
    ),
    ("one blank line", "description: Deploy\n\n  and verify.\n", "Deploy\nand verify."),
    ("multiple blank lines", "description: Deploy\n\n\n  and verify.\n", "Deploy\n\nand verify."),
    (
        "whitespace-only blank line",
        "description: Deploy\n   \n  and verify.\n",
        "Deploy\nand verify.",
    ),
    (
        "leading and trailing comments",
        "# before key\ndescription: # before value\n  # before scalar\n  Deploy\n"
        "  and verify. # after scalar\n# after value\n",
        "Deploy and verify.",
    ),
    ("trailing whitespace", "description: Deploy  \n    and verify.  \n", "Deploy and verify."),
    ("CRLF line breaks", "description: Deploy\r\n  and verify.\r\n", "Deploy and verify."),
    ("double-quoted scalar", 'description: "Deploy it\n  and more"\n', "Deploy it and more"),
    ("single-quoted scalar", "description: 'Deploy it\n  and more'\n", "Deploy it and more"),
    (
        "single-quoted apostrophe",
        "description: 'Deploy it\n  and don''t stop'\n",
        "Deploy it and don't stop",
    ),
    (
        "double-quoted blank lines",
        'description: "Deploy\n\n\n  and verify."\n',
        "Deploy\n\nand verify.",
    ),
    ("single-quoted blank line", "description: 'Deploy\n\n  and verify.'\n", "Deploy\nand verify."),
    (
        "quoted whitespace folding",
        'description: "Deploy  \n    and verify."\n',
        "Deploy and verify.",
    ),
    ("double-quoted escaped line break", 'description: "De\\\n  ploy"\n', "Deploy"),
    ("space before escaped line break", 'description: "Deploy \\\n  it"\n', "Deploy it"),
    ("escaped line break followed by blank line", 'description: "Deploy\\\n\n  it"\n', "Deploy it"),
    (
        "space before escaped line break followed by blank line",
        'description: "Deploy \\\n\n  it"\n',
        "Deploy  it",
    ),
    ("escaped leading space after line break", 'description: "Deploy\\\n  \\ it"\n', "Deploy it"),
    (
        "escaped trailing space before a folded break",
        'description: "Deploy\\ \n  it"\n',
        "Deploy  it",
    ),
    (
        "escaped break followed by multiple blank lines",
        'description: "Deploy\\\n\n\n  it"\n',
        "Deploy\nit",
    ),
    (
        "hash inside double quotes",
        'description: "Deploy\n  # still text" # comment\n',
        "Deploy # still text",
    ),
    (
        "hash inside single quotes",
        "description: 'Deploy\n  # still text' # comment\n",
        "Deploy # still text",
    ),
    (
        "colon and hash without separating spaces",
        "description: Visit https://example.com\n  for issue#123\n",
        "Visit https://example.com for issue#123",
    ),
    (
        "apostrophe in plain text before a comment",
        "description: Don't deploy # comment\n",
        "Don't deploy",
    ),
    (
        "quote in plain text before a comment",
        'description: Use a "quote # comment\n',
        'Use a "quote',
    ),
    (
        "single quote starting a plain continuation",
        "description: Deploy\n  'it # end\n",
        "Deploy 'it",
    ),
    (
        "double quote starting a plain continuation",
        'description: Deploy\n  "it # end\n',
        'Deploy "it',
    ),
    (
        "bracket and quote inside plain text",
        "description: plain [ a 'quote # comment\n",
        "plain [ a 'quote",
    ),
]


@pytest.mark.parametrize(("name", "source", "expected"), _FLOW_SCALARS)
def test_multiline_flow_scalars_folds(name: str, source: str, expected: str):
    """multiline flow scalars folds %s"""
    assert yaml.parse(source) == {"description": expected}, name
    nested = "\n".join(f"  {line}" for line in re.split(r"\r?\n", source))
    assert yaml.parse(f"metadata:\n{nested}") == {"metadata": {"description": expected}}, name


def test_ends_plain_scalars_at_sibling_keys_after_terminating_comments():
    """ends plain scalars at sibling keys after terminating comments"""
    source = "description: Deploy\n  and verify. # end\n# between keys\nenabled: true\n"
    assert yaml.parse(source) == {"description": "Deploy and verify.", "enabled": True}


def test_folds_plain_sequence_items():
    """folds plain sequence items"""
    assert yaml.parse("- Deploy\n  and verify.\n- Finish\n") == ["Deploy and verify.", "Finish"]


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        (
            "JSON-style mapping below its key",
            'example:\n  {\n    "active_anon": 1572864,\n    "active_file": 5115904\n  }\n',
            {"example": {"active_anon": 1572864, "active_file": 5115904}},
        ),
        ("closing bracket at the parent indentation", "a: [\n  1,\n  2\n]\n", {"a": [1, 2]}),
        (
            "nested collections",
            "a: {\n  b: [\n    1\n  ],\n  c: {d: 2}\n  }\n",
            {"a": {"b": [1], "c": {"d": 2}}},
        ),
        ("sibling key after the collection", "a: [\n  1\n  ]\nb: 2\n", {"a": [1], "b": 2}),
        ("comment and blank lines", "a: [1, # one\n# between\n\n  2]\n", {"a": [1, 2]}),
        (
            "quoted hash after a comma on a continuation line",
            'a: [\n  1, "a # b"\n  ]\n',
            {"a": [1, "a # b"]},
        ),
        ("multiline plain values", "a: [b\n  c, d\n\n  e]\n", {"a": ["b c", "d\ne"]}),
    ],
)
def test_multiline_flow_collections_parses(name: str, source: str, expected: object):
    """multiline flow collections parses %s"""
    assert yaml.parse(source) == expected, name


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("continuation at the parent indentation", "a: {\nb: 1 }\n"),
        ("unterminated collection before a sibling key", "a: [1,\n  2\nb: 3\n"),
        ("content after the closing bracket", "a: [1,\n  2] extra\n"),
    ],
)
def test_multiline_flow_collections_rejects(name: str, source: str):
    """multiline flow collections rejects %s"""
    with pytest.raises(ValueError):
        yaml.parse(source)


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("colon followed by space", "description: Use when: deploy\n"),
        ("colon at end of plain scalar", "description: Deploy:\n"),
        ("colon followed by tab", "description: Use when:\tdeploy\n"),
        ("colon in a continuation", "description: Deploy\n  when: ready\n"),
        ("continuation after an inline comment", "description: Deploy # end\n  and verify.\n"),
        ("continuation after a comment line", "description: Deploy\n  # end\n  and verify.\n"),
        (
            "continuation after a trailing continuation comment",
            "description: Deploy\n  and verify # end\n  again\n",
        ),
        (
            "continuation after a comment following a literal single quote",
            "description: Deploy\n  'it # end\n  again\n",
        ),
        (
            "continuation after a comment following a literal double quote",
            'description: Deploy\n  "it # end\n  again\n',
        ),
        ("unterminated double quote", 'description: "Deploy\n  and verify\n'),
        ("unterminated single quote", "description: 'Deploy\n  and verify\n"),
        ("content after closing double quote", 'description: "Deploy\n  it" extra\n'),
        ("content after closing single quote", "description: 'Deploy\n  it' extra\n"),
        ("tab-indented scalar", "description:\n\tDeploy\n"),
        ("duplicate key", "description: first\ndescription: second\n"),
    ],
)
def test_scalar_conformance_boundaries_rejects(name: str, source: str):
    """scalar conformance boundaries rejects %s"""
    with pytest.raises(ValueError):
        yaml.parse(source)


def test_preserves_numeric_decoding_and_quoted_colon_content():
    """preserves numeric decoding and quoted colon content"""
    source = "description: 123\nquoted: 'Use when: deploy'\ntrailing: \"Deploy:\"\n"
    assert yaml.parse(source) == {
        "description": 123,
        "quoted": "Use when: deploy",
        "trailing": "Deploy:",
    }


_SHAPES = [
    ("indentless sequence", "tools:\n- Read\n- Bash\n"),
    ("nested indentless sequence", "metadata:\n  tools:\n  - Read\n"),
    ("multiline plain scalar", "description: Deploy\n  and verify.\n"),
    ("multiline quoted scalar", 'description: "Deploy\n  and verify."\n'),
]


@pytest.mark.parametrize(
    ("name", "malformed"),
    [
        ("unterminated flow sequence", "broken: [one, two\n"),
        ("unterminated flow mapping", "broken: {one: two\n"),
        ("unmatched top-level line", "broken: true\nunmatched\n"),
        ("tab indentation", "broken:\n\tchild: true\n"),
        ("invalid mapping indentation", "broken:\n   child: true\n  sibling: false\n"),
        ("duplicate keys", "broken: one\nbroken: two\n"),
    ],
)
def test_rejects_alone_and_before_or_after_valid_shapes(name: str, malformed: str):
    """malformed content around compatibility shapes rejects %s alone and before or
    after valid shapes"""
    with pytest.raises(ValueError):
        yaml.parse(malformed)
    for shape, source in _SHAPES:
        with pytest.raises(ValueError):
            yaml.parse(malformed + source)
        with pytest.raises(ValueError):
            yaml.parse(source + malformed)
        assert shape, name


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("indentless mapping value", "a:\n- - 1\n  - 2\n"),
        ("indented mapping value", "a:\n  - - 1\n    - 2\n"),
        ("root sequence", "- - 1\n  - 2\n"),
        ("blank line between nested entries", "- - 1\n\n  - 2\n"),
        ("nested entry after a scalar item", "a:\n- 1\n- - 2\n"),
        ("nested mapping item", "a:\n- - b: 1\n"),
        ("single-line nested sequence", "- - 1\n"),
        ("empty nested entry", "- -\n"),
    ],
)
def test_unsupported_compact_nested_block_sequences_rejects(name: str, source: str):
    """unsupported compact nested block sequences rejects %s"""
    with pytest.raises(ValueError):
        yaml.parse(source)


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        ("mapping value", "a: one\n  - two\n", {"a": "one - two"}),
        ("sequence item", "- one\n  - two\n", ["one - two"]),
    ],
)
def test_preserves_a_dash_in_a_plain_continuation_of_a(name: str, source: str, expected: object):
    """preserves a dash in a plain continuation of a %s"""
    assert yaml.parse(source) == expected, name


@pytest.mark.parametrize(
    ("marker", "suffix"), [("---", ""), ("---", " # comment"), ("...", ""), ("...", " # comment")]
)
def test_preserves_indented_marker_as_a_mapping_value(marker: str, suffix: str):
    """preserves indented %s%s as a mapping value"""
    assert yaml.parse(f"a:\n  {marker}{suffix}\n") == {"a": marker}
    assert yaml.parse(f"metadata:\n  a:\n    {marker}{suffix}\n") == {"metadata": {"a": marker}}


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("mappings", "a: 1\n---\nb: 2\n"),
        ("sequences", "- one\n---\n- two\n"),
        ("plain scalars", "one\n---\ntwo\n"),
        ("explicit initial marker", "---\na: 1\n--- # second document\nb: 2\n"),
        ("empty first document", "---\n---\nb: 2\n"),
        ("empty trailing document", "a: 1\n---\n"),
    ],
)
def test_rejects_a_document_stream_containing(name: str, source: str):
    """rejects a document stream containing %s"""
    with pytest.raises(ValueError):
        yaml.parse(source)


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        ("mapping", "# before\n--- # start\na: 1\n... # end\n# after\n", {"a": 1}),
        ("sequence", "---\n- one\n- two\n...\n", ["one", "two"]),
        ("plain scalar", "---\none\n...\n", "one"),
        ("empty document", "---\n...\n", None),
    ],
)
def test_preserves_single_document_markers_around_a(name: str, source: str, expected: object):
    """preserves single-document markers around a %s"""
    assert yaml.parse(source) == expected, name


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        ("plain", "description: &text Deploy\n  and verify.\nalias: *text\n", "Deploy and verify."),
        (
            "single-quoted",
            "description: &text 'Deploy # first\n  # second' # end\nalias: *text\n",
            "Deploy # first # second",
        ),
        (
            "double-quoted",
            'description: &text "Deploy # first\n  # second" # end\nalias: *text\n',
            "Deploy # first # second",
        ),
    ],
)
def test_resolves_anchored_multiline_scalars(name: str, source: str, expected: str):
    """resolves anchored multiline %s scalars"""
    assert yaml.parse(source) == {"description": expected, "alias": expected}, name


def test_resolves_anchored_nested_indentless_sequences():
    """resolves anchored nested indentless sequences"""
    source = "metadata:\n  tools: &tools\n  - Read\n  - Bash\n  alias: *tools\n"
    assert yaml.parse(source) == {
        "metadata": {"tools": ["Read", "Bash"], "alias": ["Read", "Bash"]}
    }


def test_resolves_anchors_defined_inside_flow_collections():
    """resolves anchors defined inside flow collections"""
    source = (
        "mapping: {a: &value 1, b: *value}\nsequence: [&item one, *item, &empty, *empty]\n"
        "alias: *value\n"
    )
    assert yaml.parse(source) == {
        "mapping": {"a": 1, "b": 1},
        "sequence": ["one", "one", None, None],
        "alias": 1,
    }


@pytest.mark.parametrize("source", ["{a: &}", "[&item[1]]", "[&first &second 1]"])
def test_rejects_invalid_flow_anchor(source: str):
    """rejects invalid flow anchor %s"""
    with pytest.raises(ValueError):
        yaml.parse(source)


def test_preserves_hashes_in_json_style_flow_strings_without_colon_spacing():
    """preserves hashes in JSON-style flow strings without colon spacing"""
    assert yaml.parse('{"description":"Deploy # now"} # end\n') == {"description": "Deploy # now"}


def test_preserves_hashes_in_single_and_double_quoted_flow_sequence_items():
    """preserves hashes in single- and double-quoted flow sequence items"""
    source = "descriptions: [\"Deploy # now\", 'Verify # later'] # end\n"
    assert yaml.parse(source) == {"descriptions": ["Deploy # now", "Verify # later"]}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("-   name: a\n    age: 1\n", [{"name": "a", "age": 1}]),
        (
            "items:\n-   name: a\n    age: 1\n-   name: b\n    age: 2\n",
            {"items": [{"name": "a", "age": 1}, {"name": "b", "age": 2}]},
        ),
    ],
    ids=["root sequence", "indentless sequence"],
)
def test_sequence_entry_mappings_indented_past_the_dash_parses(source: str, expected: object):
    """sequence entry mappings indented past the dash parses $name"""
    assert yaml.parse(source) == expected


@pytest.mark.parametrize(
    "source",
    ["-   name: a\n  age: 1\n", "-   name: a\n   age: 1\n"],
    ids=["two spaces", "three spaces"],
)
def test_rejects_a_later_key_indented_by(source: str):
    """rejects a later key indented by %s"""
    with pytest.raises(ValueError):
        yaml.parse(source)


def test_rejects_a_tab_before_the_first_key():
    """rejects a tab before the first key"""
    with pytest.raises(ValueError, match="Tabs cannot be used for YAML indentation"):
        yaml.parse("- \tname: a\n   age: 1\n")


def test_merges_mappings_with_explicit_keys_and_earlier_sources_taking_precedence():
    """merges mappings with explicit keys and earlier sources taking precedence"""
    source = """base: &base {a: 1, b: 2}
other: &other {b: 3, c: 4}
block:
  c: 5
  <<: [*base, *other]
flow: {<<: *other, c: 5}
items:
  - <<: *base
    a: 5
"""
    result: Any = yaml.parse(source)
    assert result == {
        "base": {"a": 1, "b": 2},
        "other": {"b": 3, "c": 4},
        "block": {"a": 1, "b": 2, "c": 5},
        "flow": {"b": 3, "c": 5},
        "items": [{"a": 5, "b": 2}],
    }
    assert list(result["flow"]) == ["b", "c"]


def test_treats_quoted_merge_keys_as_ordinary_keys():
    """treats quoted merge keys as ordinary keys"""
    assert yaml.parse("\"<<\": 1\nflow: {'<<': 2}\n") == {"<<": 1, "flow": {"<<": 2}}


@pytest.mark.parametrize("source", ["<<: 1\n", "{<<: [{a: 1}, 2]}", "<<: {a: 1}\n<<: {b: 2}\n"])
def test_rejects_invalid_merge_usage_in(source: str):
    """rejects invalid merge usage in %j"""
    with pytest.raises(ValueError):
        yaml.parse(source)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("<<: 1\n", "Merge key values must be mappings at line 1"),
        ("{<<: [{a: 1}, 2]}", "Merge key values must be mappings at flow offset 16"),
        ("-   name: a\n  age: 1\n", "Unexpected indentation of 2 spaces at line 2"),
        ("<<: {a: 1}\n<<: {b: 2}\n", "Duplicate key '<<' at line 2"),
        ("a: 1\n<<: {a: 2}\na: 3\n", "Duplicate key 'a' at line 3"),
        ("- \tname: a\n", "Tabs cannot be used for YAML indentation at line 1"),
    ],
)
def test_merge_and_indentation_errors_give_effect_s_message(source: str, message: str):
    """(pyfect) printed by Effect 4.1.2 under Node"""
    with pytest.raises(ValueError) as raised:
        yaml.parse(source)
    assert str(raised.value) == message
