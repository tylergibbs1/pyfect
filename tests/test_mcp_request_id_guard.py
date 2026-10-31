"""A JSON-RPC id read from a peer is parsed (``parse_request_id``) before
it keys or cancels anything; a ``cast`` to ``RequestId`` would let a list
(unhashable) or ``True`` (equal to ``1``) through. Only the client's own
outgoing ``message["id"]``, which it numbered itself, may be cast."""

from __future__ import annotations

import re
from pathlib import Path

_AI = Path(__file__).parent.parent / "src" / "pyfect" / "ai"
_CAST = re.compile(r"""cast\(\s*["']RequestId["']\s*,\s*(?P<value>[^)]*)\)""")
_OWN_ID = 'message["id"]'


def test_request_ids_from_the_wire_are_parsed_not_cast():
    offenders = [
        f"{path.relative_to(_AI)}: {match.group()}"
        for path in sorted(_AI.rglob("*.py"))
        for match in _CAST.finditer(path.read_text())
        if match.group("value").strip() != _OWN_ID
    ]
    assert offenders == []
