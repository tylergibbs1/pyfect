"""``openapi.from_api`` keeps nothing past the option functions and API it was given.

Its cache was weakly keyed by the API, then strongly by the option functions, so a fresh
``include_annotation_key`` or ``reference_policy`` on each call (one per ``/openapi.json``
request) added a document per call forever, and an option function reaching its API kept
the API alive through its own weakly keyed entry. Like Effect's (weak on the options,
then weak on the API), the cache is now weak at every level. Found auditing
weak-keyed tables after the soak test (tests/soak) found the same flaw in the HTTP client.
"""

from __future__ import annotations

import gc
import weakref

from _gc_census import tracked_count

from pyfect.http_api import endpoint as ep
from pyfect.http_api import openapi
from pyfect.http_api.api import AnyApi, HttpApi
from pyfect.http_api.group import HttpApiGroup


def _api() -> AnyApi:
    return HttpApi.make("Api").add(HttpApiGroup.make("g").add(ep.get("get", "/users")))


def _cached_objects(calls: int) -> int:
    api = _api()
    openapi.from_api(api, include_annotation_key=lambda k: k.startswith("x-"))
    gc.collect()
    before = tracked_count()
    for _ in range(calls):
        openapi.from_api(api, include_annotation_key=lambda k: k.startswith("x-"))
    gc.collect()
    return tracked_count() - before


def test_fresh_option_functions_add_nothing_per_call() -> None:
    assert _cached_objects(200) < 200


def test_an_option_function_reaching_its_api_does_not_keep_it() -> None:
    def make() -> weakref.ref[AnyApi]:
        api = _api()
        apis = [api]  # the policy reaches its API
        openapi.from_api(api, reference_policy=lambda _c: None if apis else "never")
        return weakref.ref(api)

    ref = make()
    gc.collect()
    assert ref() is None


def test_a_call_with_the_same_options_is_made_once() -> None:
    api = _api()
    calls: list[str] = []

    def include(key: str) -> bool:
        calls.append(key)
        return False

    openapi.from_api(api)
    assert openapi.from_api(api) == openapi.from_api(api, include_annotation_key=include)
    made = len(calls)
    openapi.from_api(api, include_annotation_key=include)
    assert len(calls) == made
