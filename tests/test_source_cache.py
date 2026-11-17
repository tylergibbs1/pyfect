import gc
import sysconfig
from pathlib import Path

import _source

_FREE_THREADED = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
"""The free-threaded collector isn't generational: every collection scans the whole heap,
whatever generation it reports."""


def test_parsing_a_file_never_scans_the_whole_heap(tmp_path: Path) -> None:
    # One full collection per parsed file made the source guards hang on 3.14t.
    path = tmp_path / "module.py"
    path.write_text("def f(x):\n    return [y for y in x]\n", encoding="utf-8")
    full: list[int] = []

    def record(phase: str, info: dict[str, int]) -> None:
        if phase == "start" and (_FREE_THREADED or info["generation"] == 2):
            full.append(info["generation"])

    gc.callbacks.append(record)
    try:
        _source.tree(path)
    finally:
        gc.callbacks.remove(record)
    assert full == []
