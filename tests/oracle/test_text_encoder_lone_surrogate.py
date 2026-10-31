"""Text written as bytes outside the AI and workflow packages is encoded as
``TextEncoder`` encodes it too: a lone surrogate becomes U+FFFD, where
``str.encode()`` raised (the siblings of QA ai-workflow WF-2). Expected
values are Effect 4.0.6's under Node."""

from __future__ import annotations

import pyfect as fx
from pyfect import stream
from pyfect.cluster.sql_runner_storage import postgres_lock_namespace
from pyfect.http import server_response

_LONE = "a\ud800"
_REPLACED = b"a\xef\xbf\xbd"


def test_encode_text_replaces_a_lone_surrogate():
    """``Stream.encodeText`` of ``"a\\ud800"`` is ``[97, 239, 191, 189]``."""
    assert fx.run_sync(stream.make(_LONE).encode_text().run_collect()) == [_REPLACED]


def test_the_postgres_lock_namespace_of_a_prefix_with_a_lone_surrogate():
    """``postgresLockNamespace("a\\ud800")`` is ``1061080427``."""
    assert postgres_lock_namespace(_LONE) == 1061080427


def test_a_raw_text_response_body_replaces_a_lone_surrogate():
    response = server_response.raw(_LONE)
    client = server_response.to_client_response(response)
    assert fx.run_sync(client.bytes_.or_die()) == _REPLACED
