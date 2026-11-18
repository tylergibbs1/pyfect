"""(pyfect) Decoding ``S.RegExp`` from JSON costs about what the source's length does (#29).

CPython's compiler marks every code point of a class range one at a time, so a short source
of wide classes (``[ -\\uffff]`` repeated) cost about a millisecond per 7 bytes; Effect's
``new RegExp`` keeps ranges as ranges. The classes' total width is bounded before compiling,
a source too deep to parse is an invalid value rather than a defect, and peer sources stay
out of ``re``'s process-wide cache.
"""

from __future__ import annotations

import re

from _growth import cpu_pair
from _guards import guards

from pyfect import schema as S
from pyfect.exit import Failure, Success
from pyfect.result import Err

_decode = S.decode_unknown_exit(S.to_codec_json(S.RegExp))
_CLASSES = f"[ -{chr(0xFFFF)}]" * 1000


@guards("022fe6db", "regexp-wide-classes-compiled")
def test_wide_classes_cost_about_what_a_plain_source_does() -> None:
    plain = "a" * len(_CLASSES)
    wide, narrow = cpu_pair(
        lambda: _decode({"source": _CLASSES, "flags": ""}),
        lambda: _decode({"source": plain, "flags": ""}),
    )
    assert wide < 20 * max(narrow, 1e-4), (wide, narrow)


def test_a_source_past_the_class_budget_is_invalid() -> None:
    assert isinstance(_decode({"source": _CLASSES, "flags": "i"}), Failure)
    assert isinstance(_decode({"source": f"[ -{chr(0xFFFF)}]" * 10, "flags": "i"}), Success)
    assert isinstance(_decode({"source": "[\\u4e00-\\u9fff]+", "flags": ""}), Success)


def test_a_source_too_deep_to_parse_is_an_invalid_value() -> None:
    found = _decode({"source": "(" * 5000 + ")" * 5000, "flags": ""})
    assert isinstance(found, Failure)
    assert isinstance(found.cause.find_defect(), Err)


def test_decoded_sources_stay_out_of_the_re_cache() -> None:
    source = "peer-source-" + "x" * 50
    decoded = _decode({"source": source, "flags": "m"})
    assert isinstance(decoded, Success)
    assert decoded.value.pattern == source
    assert decoded.value.flags == re.MULTILINE | re.UNICODE
    cache = getattr(re, "_cache", {}) | getattr(re, "_cache2", {})
    assert all(source not in str(key) for key in cache)
