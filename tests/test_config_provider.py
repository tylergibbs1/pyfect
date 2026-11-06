"""pyfect-specific ConfigProvider behaviour: Python inputs, ``os.environ``,
the default reference and real file-system errors (each checked against
Effect under Node where Effect has the same case)."""

import math
import os
from pathlib import Path
from typing import Never

import pytest

import pyfect as fx
from pyfect import config_provider as cp
from pyfect import layer
from pyfect.config_provider import Array, Record, SourceError, Value
from pyfect.platform_error import BadResource, NotFound


def _load(
    provider: cp.ConfigProvider, path: cp.PathInput
) -> fx.Ok[cp.Node | None] | fx.Err[SourceError]:
    return fx.run_blocking(provider.load(path).result())


def test_from_env_copies_os_environ_when_made(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYFECT_TEST_EARLY", "set before")
    provider = cp.from_env()
    monkeypatch.setenv("PYFECT_TEST_LATE", "set later")

    assert _load(provider, ["PYFECT_TEST_EARLY"]) == fx.Ok(Value("set before"))
    assert _load(provider, ["PYFECT", "TEST", "EARLY"]) == fx.Ok(Value("set before"))
    assert _load(provider, ["PYFECT_TEST_LATE"]) == fx.Ok(None)


def test_the_current_provider_defaults_to_the_environment():
    found = fx.run_blocking(
        fx.CurrentConfigProvider().flat_map(lambda p: p.load(["PATH"])).result()
    )

    assert found == fx.Ok(Value(os.environ["PATH"]))


def test_load_takes_a_tuple_or_a_list():
    provider = cp.from_env(env={"A_0": "x"})

    assert _load(provider, ("A", 0)) == _load(provider, ["A", 0]) == fx.Ok(Value("x"))


def test_from_unknown_writes_scalars_as_effect_does():
    provider = cp.from_unknown(
        {"yes": True, "no": False, "whole": 3.0, "half": 0.5, "nan": math.nan, "inf": -math.inf}
    )

    assert _load(provider, ["yes"]) == fx.Ok(Value("true"))
    assert _load(provider, ["no"]) == fx.Ok(Value("false"))
    assert _load(provider, ["whole"]) == fx.Ok(Value("3"))
    assert _load(provider, ["half"]) == fx.Ok(Value("0.5"))
    assert _load(provider, ["nan"]) == fx.Ok(Value("NaN"))
    assert _load(provider, ["inf"]) == fx.Ok(Value("-Infinity"))


def test_from_unknown_reads_tuples_as_arrays_and_rejects_non_index_segments():
    provider = cp.from_unknown({"items": ("a", "b")})

    assert _load(provider, ["items"]) == fx.Ok(Array(2))
    assert _load(provider, ["items", 1]) == fx.Ok(Value("b"))
    assert _load(provider, ["items", "1"]) == fx.Ok(None)
    assert _load(provider, ["items", True]) == fx.Ok(None)
    assert _load(provider, ["items", -1]) == fx.Ok(None)


def test_an_array_node_cannot_have_a_negative_length():
    with pytest.raises(ValueError, match="length"):
        Array(-1)


def test_record_nodes_compare_by_keys_and_value():
    assert Record(frozenset({"a", "b"}), "v") == Record(frozenset({"b", "a"}), "v")
    assert Record(frozenset({"a"})) != Record(frozenset({"a"}), "")


def _live[A, E](eff: fx.Effect[A, E, fx.FileSystem | fx.Path]) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide(layer.merge(fx.file_system.layer, fx.path.layer)))


def _provider(
    eff: fx.Effect[cp.ConfigProvider, Never, fx.FileSystem | fx.Path],
) -> cp.ConfigProvider:
    return fx.run_blocking(_live(eff))


def test_from_dot_env_fails_with_not_found_for_a_missing_file(tmp_path: Path):
    path = tmp_path / "absent.env"
    result = fx.run_blocking(_live(cp.from_dot_env(path).result()))

    assert isinstance(result, fx.Err)
    assert isinstance(result.error.reason, NotFound)
    assert result.error.reason.path_or_descriptor == str(path)
    assert isinstance(result.error.cause, FileNotFoundError)


def test_from_dir_fails_when_a_path_descends_through_a_file(tmp_path: Path):
    # Effect: ENOTDIR is a BadResource error, not NotFound, so it is a SourceError.
    (tmp_path / "secret").write_text("value")
    result = _load(_provider(cp.from_dir(tmp_path)), ["secret", "inner"])

    assert isinstance(result, fx.Err)
    assert result.error.message == f"Failed to read file at {tmp_path}/secret/inner"
    assert isinstance(result.error.cause, fx.PlatformError)
    assert isinstance(result.error.cause.reason, BadResource)
    assert isinstance(result.error.cause.cause, NotADirectoryError)


def test_from_dir_joins_a_segment_starting_with_a_separator_below_the_root(tmp_path: Path):
    # As Node's path.join("/root", "/name") is "/root/name".
    (tmp_path / "name").write_text("inside")

    assert _load(_provider(cp.from_dir(tmp_path)), ["/name"]) == fx.Ok(Value("inside"))


def test_from_dir_reads_the_root_as_a_record_of_entries(tmp_path: Path):
    (tmp_path / "a").write_text("1")
    (tmp_path / "b").mkdir()

    assert _load(_provider(cp.from_dir(tmp_path)), []) == fx.Ok(Record(frozenset({"a", "b"})))


def test_constant_case_follows_effects_config_case():
    # Printed by Effect's String.configCase under Node.
    cases = {
        "XMLHttpRequest": "XML_HTTP_REQUEST",
        "ABCdef": "AB_CDEF",
        "v2API": "V2_API",
        "HTTP2Server": "HTTP2_SERVER",
        "_leading": "LEADING",
        "a__b": "A_B",
        "straße": "STRA_E",
    }
    env = {expected: name for name, expected in cases.items()}
    provider = cp.from_env(env=env).constant_case()

    for name in cases:
        assert _load(provider, [name]) == fx.Ok(Value(name))


def test_dot_env_parsing_matches_effect():
    # Each expected value was printed by Effect's fromDotEnvContents under Node.
    contents = "\n".join(
        [
            "KEY: value",
            "K2 = spaced  ",
            "export  X=1",
            'ESCAPED="a\\"b"',
            "HASH=a#b",
            "SINGLE='a'b'",
            'TRAILING="v" # c',
            "my.key-1=v",
            'TABS="\\n\\r\\t"',
            "RAW='\\n'",
            "MULTI=`multi",
            "line`",
            "  INDENT=1",
            "#COMMENTED=2",
        ]
    )
    provider = cp.from_dot_env_contents(contents + "\r\nCRLF=3\rCR=4")
    expected = {
        "KEY": "value",
        "K2": "spaced",
        "X": "1",
        "ESCAPED": 'a\\"b',
        "HASH": "a",
        "SINGLE": "a'b",
        "TRAILING": "v",
        "my.key-1": "v",
        "TABS": "\n\r\\t",
        "RAW": "\\n",
        "MULTI": "multi\nline",
        "INDENT": "1",
        "CRLF": "3",
        "CR": "4",
    }
    for key, value in expected.items():
        assert _load(provider, [key]) == fx.Ok(Value(value)), key
    assert _load(provider, ["COMMENTED"]) == fx.Ok(None)


def test_dot_env_expansion_matches_effect():
    # Each expected value was printed by Effect's fromDotEnvContents under Node.
    cases = [
        ("A=1\nB=2\nV=$A$B", "12"),
        ("B=b\nV=${A:-${B:-c}}", "b"),
        ("A=1\nV=\\${A}", "${A}"),
        ("A=1\nV=${A}}", "1}"),
        ("A=1\nV=${A:-x}y${A}", "1y1"),
        ("V=${UNSET:-a${B}c}\nB=bb", "abbc"),
        ("A=$B\nB=${A:-dflt}", "dflt"),
        ("A='$B'\nB=1\nV=$A", "1"),
    ]
    for contents, value in cases:
        provider = cp.from_dot_env_contents(contents, expand_variables=True)
        assert _load(provider, ["V"] if "V=" in contents else ["A"]) == fx.Ok(Value(value)), (
            contents
        )


def test_dot_env_whitespace_and_line_ends_are_javascripts():
    # Printed by Effect's fromDotEnvContents under Node: JavaScript's \s takes
    # a byte-order mark and no-break spaces but not \x1c or \x85, and its
    # multiline ^ and $ also break at U+2028 / U+2029.
    cases = [
        ("\ufeffA=1\nB=2", {"A": "1", "B": "2"}),
        ("A=\u00a0x\u00a0\nB=2", {"A": "x", "B": "2"}),
        ("A=1 # c\u2028B=2\nC=3", {"A": "1", "B": "2", "C": "3"}),
        ("A=\x1cx\x1c\nB=2", {"A": "\x1cx\x1c", "B": "2"}),
        ("A=x\x85\nB=2", {"A": "x\x85", "B": "2"}),
        ("A=1\u2028B=2", {"A": "1\u2028B=2"}),
    ]
    for contents, expected in cases:
        provider = cp.from_dot_env_contents(contents)
        for key in ("A", "B", "C"):
            want = Value(expected[key]) if key in expected else None
            assert _load(provider, [key]) == fx.Ok(want), (contents, key)


def test_from_dot_env_reads_a_file_with_a_byte_order_mark(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8-sig")
    loaded = fx.run_blocking(_live(cp.from_dot_env(path).result()))

    assert isinstance(loaded, fx.Ok)
    assert _load(loaded.value, ["A"]) == fx.Ok(Value("1"))


def test_from_unknown_writes_floats_as_javascripts_string():
    # Printed by Effect's fromUnknown under Node.
    cases = {
        1e-5: "0.00001",
        1.5e-7: "1.5e-7",
        0.000001: "0.000001",
        1e-7: "1e-7",
        123456789012345680000.0: "123456789012345680000",
        1e21: "1e+21",
        1.5e21: "1.5e+21",
        2.5e-300: "2.5e-300",
        0.1: "0.1",
        123.456: "123.456",
        -1e-7: "-1e-7",
        5e-324: "5e-324",
        1.7976931348623157e308: "1.7976931348623157e+308",
        1e100: "1e+100",
        12345.678e10: "123456780000000",
        0.00001234: "0.00001234",
        -0.0: "0",
    }
    provider = cp.from_unknown(list(cases))

    for index, text in enumerate(cases.values()):
        assert _load(provider, [index]) == fx.Ok(Value(text)), text


def test_from_env_record_reads_its_names_when_made_and_its_values_at_each_lookup():
    # Effect builds the name trie once and reads values from the record:
    # printed by Effect's fromEnvRecord under Node.
    env = {"A_B": "1"}
    provider = cp.from_env_record(env)
    env.update({"A_C": "2", "X": "3", "X_Y": "4"})

    assert _load(provider, ["A"]) == fx.Ok(Record(frozenset({"B"})))
    assert _load(provider, ["A", "C"]) == fx.Ok(Value("2"))
    assert _load(provider, ["X"]) == fx.Ok(Value("3"))
    assert _load(provider, ["X", "Y"]) == fx.Ok(Value("4"))


@pytest.mark.parametrize(
    "path", [("..",), ("..", "outside"), ("inner", "..", "..", "outside"), ("inner/../../outside",)]
)
def test_from_dir_does_not_read_above_the_root(tmp_path: Path, path: tuple[str, ...]):
    (tmp_path / "outside").write_text("secret")
    root = tmp_path / "root"
    (root / "inner").mkdir(parents=True)

    assert _load(_provider(cp.from_dir(root)), path) == fx.Ok(None)


def test_from_dir_reads_a_dot_dot_that_stays_below_the_root(tmp_path: Path):
    (tmp_path / "inner").mkdir()
    (tmp_path / "name").write_text("inside")

    assert _load(_provider(cp.from_dir(tmp_path)), ["inner", "..", "name"]) == fx.Ok(
        Value("inside")
    )
