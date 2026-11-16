"""Keys are loaded through ``pyfect.crypto._lib``'s loaders, never
``cryptography``'s directly.

``serialization.load_der_public_key`` raises ``ValueError``, ``TypeError`` or
``UnsupportedAlgorithm`` for bytes it cannot read; catching only the first two
once let an SPKI naming an unknown algorithm die instead of failing with
``InvalidKey`` (found by tests/fuzz). The loaders return ``None`` for all three.
"""

import re

import _source

SRC = _source.SRC
LIB = SRC / "crypto" / "_lib.py"
DIRECT = re.compile(r"serialization\.load_\w+|from cryptography\S* import .*\bload_\w+")


def test_keys_are_loaded_only_through_the_lib_loaders():
    offenders = [
        str(path.relative_to(SRC))
        for path in _source.files(SRC)
        if path != LIB
        for line in _source.text(path).splitlines()
        if DIRECT.search(line)
    ]
    assert not offenders, f"load keys with pyfect.crypto._lib's loaders: {offenders}"
