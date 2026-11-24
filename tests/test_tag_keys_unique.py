"""A tag's key is its identity, so two modules declaring a tag with one literal key would share a
service, and a run importing both warns with ``DuplicateTagKeyWarning`` (an error under pytest)
only when the two land on one worker. This check finds such keys in every file at once. A key
may repeat within one file, where a test shares a service on purpose and says so."""

import ast
import re
from collections import defaultdict
from pathlib import Path

import _source

ROOT = Path(__file__).parent.parent
_DIRS = ("src", "tests", "examples", "website/snippets", "benchmarks")
_KEYWORD = re.compile(r"\bkey=[\"']([^\"']+)[\"']")


def _class_keys(path: Path) -> set[str]:
    return {
        keyword.value.value
        for node in ast.walk(_source.tree(path))
        if isinstance(node, ast.ClassDef)
        for keyword in node.keywords
        if keyword.arg == "key"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }


def test_no_two_files_declare_a_tag_with_one_key() -> None:
    # Any ``key="..."`` text first (cheap), then the class keywords of the files sharing one.
    files: defaultdict[str, set[Path]] = defaultdict(set)
    for directory in _DIRS:
        for path in _source.files(ROOT / directory):
            for key in _KEYWORD.findall(_source.text(path)):
                files[key].add(path)
    shared = {
        key: sorted(path.relative_to(ROOT).as_posix() for path in tags)
        for key, where in files.items()
        if len(where) > 1 and len(tags := {path for path in where if key in _class_keys(path)}) > 1
    }
    assert shared == {}, "give each tag its own key (a tag's key is its identity)"
