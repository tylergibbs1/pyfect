"""The title guard counts a title as ported only by a test that names its Effect file."""

from __future__ import annotations

from pathlib import Path

from _effect_titles import ambiguous_mentions, is_ported, named_files, read_ports

_FILES = (
    "effect/test/Effect.test.ts",
    "effect/test/Stream.test.ts",
    "sql/pg/test/Client.test.ts",
    "sql/mysql2/test/Client.test.ts",
    "effect/test/http/FindMyWay/regex.test.ts",
)


def _ports(tmp_path: Path, source: str):
    module = tmp_path / "test_port.py"
    module.write_text(source)
    return read_ports([module], _FILES)


def test_a_title_counts_for_the_file_the_module_docstring_names(tmp_path: Path) -> None:
    ports = _ports(
        tmp_path,
        '"""Ports of ``Stream.test.ts``."""\n\ndef test_x():\n    """drains a stream"""\n',
    )
    assert is_ported("drains a stream", ports["effect/test/Stream.test.ts"])
    assert "effect/test/Effect.test.ts" not in ports


def test_a_test_docstring_adds_its_own_file(tmp_path: Path) -> None:
    ports = _ports(
        tmp_path,
        '"""Ports of ``Stream.test.ts``."""\n\n'
        'def test_x():\n    """Effect.test.ts / bounded"""\n\n'
        'def test_y():\n    """unbounded"""\n',
    )
    assert is_ported("bounded", ports["effect/test/Effect.test.ts"])
    assert not is_ported("unbounded", ports["effect/test/Effect.test.ts"])
    assert is_ported("unbounded", ports["effect/test/Stream.test.ts"])


def test_a_module_naming_no_effect_file_ports_nothing(tmp_path: Path) -> None:
    assert _ports(tmp_path, 'def test_x():\n    """bounded"""\n') == {}


def test_titles_with_interpolations_match_per_file(tmp_path: Path) -> None:
    ports = _ports(
        tmp_path,
        '"""Ports of ``Effect.test.ts``."""\n\ndef test_x():\n    """retries ${n} times"""\n',
    )
    assert is_ported("retries ${count} times", ports["effect/test/Effect.test.ts"])


def test_npm_package_names_and_globs_name_files() -> None:
    assert named_files("``sql-pg/test/Client.test.ts``", _FILES) == {"sql/pg/test/Client.test.ts"}
    assert named_files("``http/FindMyWay/*.test.ts``", _FILES) == {
        "effect/test/http/FindMyWay/regex.test.ts"
    }


def test_a_bare_name_of_several_files_is_ambiguous() -> None:
    assert ambiguous_mentions("``Client.test.ts``", _FILES) == ["Client.test.ts"]
    assert ambiguous_mentions("``sql-mysql2/test/Client.test.ts``", _FILES) == []
