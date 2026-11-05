"""Effect's LayerHttpRequestScoped.test.ts re-runs its shared conformance
suites (Tools, Resources, Prompts, Completion, stateless BaseProtocol) in
request mode. Here each 2026-07-28 test of those modules runs again with its
``stdio_harness`` and ``conformance`` swapped for ones speaking to
``layer_http_request_scoped``: the tests below are those same functions."""

from __future__ import annotations

import functools
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

import pyfect as fx
from pyfect.ai import mcp_protocol as P
from pyfect.scope import Scope

from . import (
    test_mcp_conformance_base_protocol,
    test_mcp_conformance_prompts,
    test_mcp_conformance_resources,
    test_mcp_conformance_tools,
)
from ._mcp_http import (
    SERVER_NAME,
    Conformance,
    Json,
    Session,
    http_harness,
    read_message,
    server_layer,
)

_SUITES = (
    test_mcp_conformance_tools,
    test_mcp_conformance_prompts,
    test_mcp_conformance_resources,
)
# Effect's two "should send no response" titles read a stdio harness in either mode.
_STATELESS_BASE_PROTOCOL = (
    "test_should_preserve_string_and_numeric_identifiers_when_requests_succeed",
    "test_should_reject_a_request_when_its_json_rpc_version_is_invalid",
    "test_should_reject_a_request_when_its_identifier_is_not_a_string_or_integer",
    "test_should_return_method_not_found_when_the_requested_method_is_unknown",
    "test_should_return_invalid_params_when_request_parameters_do_not_match_the_method_schema",
    "test_should_send_exactly_one_result_response_when_a_request_succeeds",
    "test_should_send_exactly_one_error_response_when_a_request_fails",
    "test_should_return_a_parse_error_when_a_json_message_is_malformed",
    "test_should_return_invalid_request_when_a_json_rpc_message_omits_its_method",
)


@dataclass
class _RequestModeHarness:
    """What the suites call on a ``StdioHarness``, as POSTs of their own."""

    protocol: P.AnyProtocolAdapter
    conformance: Conformance
    session: Session
    capabilities: Json
    next_id: int = 1
    answers: list[Json] = field(default_factory=list[Json])

    def send_request(
        self, method: str, params: Json | None = None, id: object = None
    ) -> fx.Effect[Json]:
        if id is None:
            id = self.next_id
            self.next_id += 1
        body: Json = {"jsonrpc": "2.0", "id": id, "method": method}
        if params is not None:
            body["params"] = params
        return self.conformance.send(
            self.session, body, client_capabilities=self.capabilities
        ).flat_map(read_message)

    def initialize(self, capabilities: Json | None = None) -> fx.Effect[Json]:
        self.capabilities = capabilities or {}
        return self.send_request("server/discover", {})

    def send(self, message: Json) -> fx.Effect[None]:
        """POST ``message``; what it answers is left for ``receive``."""

        @fx.gen
        def run():
            response = yield from self.conformance.send(self.session, message)
            if response.status != 202:
                self.answers.append((yield from read_message(response)))

        return run

    def send_notification(self, method: str, params: Json | None = None) -> fx.Effect[None]:
        return self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def receive(self) -> fx.Effect[Json]:
        """The next answer; a POST has only its own, so none means none comes."""
        return fx.suspend(lambda: fx.succeed(self.answers.pop(0)) if self.answers else fx.never)


def _request_mode_harness(
    protocol: P.AnyProtocolAdapter,
    protocols: object = None,
    *registrations: fx.Effect[None, Any, Any],
    instructions: str | None = None,
) -> fx.Effect[_RequestModeHarness, Any, Scope]:
    def registered() -> fx.Effect[None, Any, Any]:
        return fx.for_each(list(registrations), lambda registration: registration).as_void()

    app = server_layer(
        SERVER_NAME, (protocol,), registered(), mode="request", instructions=instructions
    )

    @fx.gen
    def run():
        conformance = Conformance(protocol, (yield from http_harness(app)))
        session = yield from conformance.initialize()
        return _RequestModeHarness(protocol, conformance, session, {})

    return run


def _request_mode_conformance(protocol: P.AnyProtocolAdapter) -> fx.Effect[Conformance, Any, Scope]:
    app = server_layer(SERVER_NAME, (protocol,), mode="request")
    return http_harness(app).map(lambda harness: Conformance(protocol, harness))


@pytest.fixture(autouse=True)
def _request_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for suite in _SUITES:
        monkeypatch.setattr(suite, "stdio_harness", _request_mode_harness)
    monkeypatch.setattr(test_mcp_conformance_base_protocol, "stdio_harness", _request_mode_harness)
    monkeypatch.setattr(
        test_mcp_conformance_base_protocol, "conformance", _request_mode_conformance
    )
    yield


def _modern_run(test: Any) -> Any | None:
    """``test`` for 2026-07-28 only; ``None`` when it has no such run."""
    marks = [m for m in getattr(test, "pytestmark", ()) if m.name == "parametrize"]
    protocols = [m for m in marks if m.args[0] == "protocol"]
    if not protocols:
        return None
    modern = [p for p in protocols[0].args[1] if p.is_stateless]
    if not modern:
        return None

    @functools.wraps(test)
    def run(*args: Any, **kwargs: Any) -> Any:
        return test(*args, **kwargs)

    others = [m for m in test.pytestmark if m is not protocols[0]]
    cast("Any", run).pytestmark = [
        *others,
        pytest.mark.parametrize("protocol", modern, ids=lambda p: p.protocol_version).mark,
    ]
    return run


for _suite in _SUITES:
    for _name, _test in list(vars(_suite).items()):
        if _name.startswith("test_") and callable(_test):
            _run = _modern_run(_test)
            if _run is not None:
                globals()[f"test_{_suite.__name__.rsplit('_', 1)[-1]}__{_name[5:]}"] = _run

for _name in _STATELESS_BASE_PROTOCOL:
    globals()[f"test_base_protocol__{_name[5:]}"] = getattr(
        test_mcp_conformance_base_protocol, _name
    )
