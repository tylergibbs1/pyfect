"""What a server logs, and answers, for a request that does not decode
(dogfood beacon #13). The expected lines are Effect 4.0.6's, run under Node
on the same API through ``HttpRouter.toWebHandler`` with its default logger:

    [..] INFO (#4) http.span=2ms: HttpApiSchemaError: Payload {
      [cause]: SchemaError: Missing key
        at ["url"]
    } { 'http.method': 'POST', 'http.url': '/monitors', 'http.status': 400 }

and an empty 400 body; pyfect names the classes as Python does.
``builder.layer(api, schema_error_details=True)``, off by default as Effect
has none, sends the issue in the body.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import json
import re
from typing import Any

import pytest

from pyfect import effect, layer
from pyfect import schema as S
from pyfect.http import router, server
from pyfect.http.web import WebRequest
from pyfect.http_api import builder
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup

from ._http_api import struct

_ADD = ep.post("add", "/monitors", payload=struct({"url": S.String}), success=S.String)
_GROUP = HttpApiGroup.make("monitors").add(_ADD)
_API = HttpApi.make("Api").add(_GROUP)
_LIVE = builder.group(
    _API, _GROUP, lambda h: h.handle(_GROUP.endpoints["add"])(lambda _: effect.succeed("ok"))
)


def _post_empty_object(**options: Any) -> tuple[int, bytes]:
    """POST ``{}`` (no ``url``): the status, the body and what was logged."""
    app = builder.layer(_API, **options).pipe(layer.provide(_LIVE))

    async def main() -> tuple[int, bytes]:
        made = router.to_web_handler(app.pipe(layer.provide(server.layer_services)))
        try:
            response = await made.handler(
                WebRequest(
                    "http://localhost/monitors",
                    method="POST",
                    headers={"content-type": "application/json"},
                    body=b"{}",
                )
            )
            return response.status, (await response.text()).encode()
        finally:
            await made.dispose()

    return asyncio.run(main())


def test_a_payload_that_does_not_decode_logs_its_cause_as_effect_renders_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status, body = _post_empty_object()
    logged = capsys.readouterr().out
    assert (status, body) == (400, b"")
    line = re.sub(r"^\[[^\]]+\] INFO \(#\d+\) http\.span=\d+ms: ", "", logged)
    assert line == (
        "pyfect.http_api.error.HttpApiSchemaError: Payload {\n"
        '  [cause]: pyfect.schema.SchemaError: Missing key\n    at ["url"]\n'
        "} {'http.method': 'POST', 'http.url': '/monitors', 'http.status': 400}\n"
    )


def test_schema_error_details_sends_the_issue_in_the_400_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status, body = _post_empty_object(schema_error_details=True)
    assert status == 400
    assert json.loads(body) == {
        "_tag": "HttpApiSchemaError",
        "kind": "Payload",
        "message": 'Missing key\n  at ["url"]',
    }
    # The failure is still what the request logs.
    assert "HttpApiSchemaError: Payload {" in capsys.readouterr().out
