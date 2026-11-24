"""Ports of Effect's ``http/FindMyWay/*.test.ts``.

Each test's docstring is the Effect test title. ``Router[A]()`` is
``FindMyWay.make<A>()`` and a missing route is ``None``.

Omitted, with the reason:

- ``returns undefined for method names inherited from Object.prototype``,
  ``preserves prototype-sensitive parameter names as own properties``,
  ``builds null-prototype params for static and parameterized routes``,
  ``does not read inherited static child entries``: Python dicts have no
  prototype; the parameter values are checked by the other tests.
- ``does not compile parameter names with Function``: nothing in Python
  compiles code from parameter names.
"""

from collections.abc import Callable

import pytest
from _growth import assert_near_linear

from pyfect.http.find_my_way import FindResult, Router, RouterConfig, strict_config


def _insensitive() -> Router[bool]:
    return Router(RouterConfig(case_sensitive=False))


def _params[A](result: FindResult[A] | None) -> dict[str, str] | None:
    return None if result is None else result.params


# --- case-insensitive ----------------------------------------------------------------


def test_case_insensitive_static_routes_of_level_1() -> None:
    """case insensitive static routes of level 1"""
    router = _insensitive()
    router.on("GET", "/woo", True)
    assert router.find("GET", "/woo") is not None


def test_case_insensitive_static_routes_of_level_2() -> None:
    """case insensitive static routes of level 2"""
    router = _insensitive()
    router.on("GET", "/foo/woo", True)
    assert router.find("GET", "/FoO/WOO") is not None


def test_case_insensitive_static_routes_of_level_3() -> None:
    """case insensitive static routes of level 3"""
    router = _insensitive()
    router.on("GET", "/foo/bar/woo", True)
    assert router.find("GET", "/Foo/bAR/WoO") is not None


def test_parametric_case_insensitive() -> None:
    """parametric case insensitive"""
    router = _insensitive()
    router.on("GET", "/foo/:param", True)
    assert _params(router.find("GET", "/Foo/bAR")) == {"param": "bAR"}


def test_parametric_case_insensitive_with_a_static_part() -> None:
    """parametric case insensitive with a static part"""
    router = _insensitive()
    router.on("GET", "/foo/my-:param", True)
    assert _params(router.find("GET", "/Foo/MY-bAR")) == {"param": "bAR"}


def test_parametric_case_insensitive_with_capital_letter() -> None:
    """parametric case insensitive with capital letter"""
    router = _insensitive()
    router.on("GET", "/foo/:Param", True)
    assert _params(router.find("GET", "/Foo/bAR")) == {"Param": "bAR"}


def test_case_insensitive_with_capital_letter_in_static_path_with_param() -> None:
    """case insensitive with capital letter in static path with param"""
    router = _insensitive()
    router.on("GET", "/Foo/bar/:param", True)
    assert _params(router.find("GET", "/foo/bar/baZ")) == {"param": "baZ"}


def test_case_insensitive_with_multiple_paths_containing_capital_letter() -> None:
    """case insensitive with multiple paths containing capital letter in static path with param"""
    router = _insensitive()
    router.on("GET", "/Foo/bar/:param", True)
    router.on("GET", "/Foo/baz/:param", True)
    assert _params(router.find("GET", "/foo/bar/baZ")) == {"param": "baZ"}
    assert _params(router.find("GET", "/foo/bar/baR")) == {"param": "baR"}


def test_case_insensitive_with_multiple_mixed_case_params_within_same_slash_couple() -> None:
    """case insensitive with multiple mixed-case params within same slash couple"""
    router = _insensitive()
    router.on("GET", "/foo/:param1-:param2", True)
    assert _params(router.find("GET", "/FOO/My-bAR")) == {"param1": "My", "param2": "bAR"}


def test_case_insensitive_with_multiple_mixed_case_params() -> None:
    """case insensitive with multiple mixed-case params"""
    router = _insensitive()
    router.on("GET", "/foo/:param1/:param2", True)
    assert _params(router.find("GET", "/FOO/My/bAR")) == {"param1": "My", "param2": "bAR"}


def test_case_insensitive_with_wildcard() -> None:
    """case insensitive with wildcard"""
    router = _insensitive()
    router.on("GET", "/foo/*", True)
    assert _params(router.find("GET", "/FOO/bAR")) == {"*": "bAR"}


def test_parametric_case_insensitive_with_multiple_routes() -> None:
    """parametric case insensitive with multiple routes"""
    router = _insensitive()
    tests = [
        ("POST", "/foo/:param/Static/:userId/Save", "/foo/bAR/static/one/SAVE",
         {"param": "bAR", "userId": "one"}),
        ("POST", "/foo/:param/Static/:userId/Update", "/fOO/Bar/Static/two/update",
         {"param": "Bar", "userId": "two"}),
        ("POST", "/foo/:param/Static/:userId/CANCEL", "/Foo/bAR/STATIC/THREE/cAnCeL",
         {"param": "bAR", "userId": "THREE"}),
    ]  # fmt: skip
    for method, path, _, _ in tests:
        router.on(method, path, True)
    for method, _, url, params in tests:
        assert _params(router.find(method, url)) == params


# --- matching order, methods ------------------------------------------------------------


def test_matching_order() -> None:
    """Matching order"""
    router = Router[bool]()
    router.on("GET", "/foo/bar/*", True)
    router.on("GET", "/foo/:param/static", True)
    assert _params(router.find("GET", "/foo/bar/static")) == {"*": "static"}
    assert _params(router.find("GET", "/foo/value/static")) == {"param": "value"}


def test_registers_query_with_all() -> None:
    """registers QUERY with all"""
    router = Router[bool]()
    router.all("/all", True)
    result = router.find("QUERY", "/all")
    assert result is not None
    assert result.handler is True


# --- optional params ----------------------------------------------------------------


def test_route_with_optional_parameter() -> None:
    """Test route with optional parameter"""
    router = Router[bool]()
    router.on("GET", "/a/:param/b/:optional?", True)
    assert _params(router.find("GET", "/a/foo-bar/b")) == {"param": "foo-bar"}
    assert _params(router.find("GET", "/a/foo-bar/b/foo")) == {
        "param": "foo-bar",
        "optional": "foo",
    }


def test_for_duplicate_route_with_optional_param() -> None:
    """Test for duplicate route with optional param"""
    router = Router[bool]()
    router.on("GET", "/foo/:bar?", True)
    with pytest.raises(ValueError, match="already declared"):
        router.on("GET", "/foo", True)


def test_for_param_with_question_mark_not_at_the_end() -> None:
    """Test for param with ? not at the end"""
    router = Router[bool]()
    with pytest.raises(ValueError, match="last parameter"):
        router.on("GET", "/foo/:bar?/baz", True)


def test_multi_parametric_route_with_optional_param() -> None:
    """Multi parametric route with optional param"""
    router = Router[bool]()
    router.on("GET", "/a/:p1-:p2?", True)
    assert _params(router.find("GET", "/a/foo-bar-baz")) == {"p1": "foo-bar", "p2": "baz"}
    assert _params(router.find("GET", "/a")) == {}


def test_optional_parameter_at_root() -> None:
    """Optional parameter at root"""
    router = Router[bool]()
    router.on("GET", "/:optional?", True)
    assert _params(router.find("GET", "/")) == {}
    assert _params(router.find("GET", "/foo")) == {"optional": "foo"}


def test_optional_parameter_with_ignore_trailing_slash_true() -> None:
    """Optional Parameter with ignoreTrailingSlash = true"""
    router = Router[bool](RouterConfig(ignore_trailing_slash=True, ignore_duplicate_slashes=False))
    router.on("GET", "/test/hello/:optional?", True)
    assert _params(router.find("GET", "/test/hello/")) == {}
    assert _params(router.find("GET", "/test/hello")) == {}
    assert _params(router.find("GET", "/test/hello/foo")) == {"optional": "foo"}
    assert _params(router.find("GET", "/test/hello/foo/")) == {"optional": "foo"}


def test_optional_parameter_with_ignore_trailing_slash_false() -> None:
    """Optional Parameter with ignoreTrailingSlash = false"""
    router = Router[bool](RouterConfig(ignore_trailing_slash=False, ignore_duplicate_slashes=False))
    router.on("GET", "/test/hello/:optional?", True)
    assert _params(router.find("GET", "/test/hello/")) == {"optional": ""}
    assert _params(router.find("GET", "/test/hello")) == {}
    assert _params(router.find("GET", "/test/hello/foo")) == {"optional": "foo"}
    assert router.find("GET", "/test/hello/foo/") is None


def test_optional_parameter_with_ignore_duplicate_slashes_true() -> None:
    """Optional Parameter with ignoreDuplicateSlashes = true"""
    router = Router[bool](RouterConfig(ignore_duplicate_slashes=True))
    router.on("GET", "/test/hello/:optional?", True)
    assert _params(router.find("GET", "/test//hello")) == {}
    assert _params(router.find("GET", "/test/hello")) == {}
    assert _params(router.find("GET", "/test/hello/foo")) == {"optional": "foo"}
    assert _params(router.find("GET", "/test//hello//foo")) == {"optional": "foo"}


def test_optional_parameter_with_ignore_duplicate_slashes_false() -> None:
    """Optional Parameter with ignoreDuplicateSlashes = false"""
    router = Router[bool](RouterConfig(ignore_duplicate_slashes=False))
    router.on("GET", "/test/hello/:optional?", True)
    assert router.find("GET", "/test//hello") is None
    assert _params(router.find("GET", "/test/hello")) == {}
    assert _params(router.find("GET", "/test/hello/foo")) == {"optional": "foo"}
    assert router.find("GET", "/test//hello//foo") is None


# --- params collisions ---------------------------------------------------------------


def _handler[A](router: Router[A], path: str) -> A | None:
    result = router.find("GET", path)
    return None if result is None else result.handler


def test_should_setup_parametric_and_regexp_node() -> None:
    """should setup parametric and regexp node"""
    router = Router[int]()
    router.on("GET", "/foo/:bar", 1)
    router.on("GET", "/foo/:bar(123)", 2)
    assert _handler(router, "/foo/value") == 1
    assert _handler(router, "/foo/123") == 2


def test_should_setup_parametric_and_multi_parametric_node() -> None:
    """should setup parametric and multi-parametric node"""
    router = Router[int]()
    router.on("GET", "/foo/:bar", 1)
    router.on("GET", "/foo/:bar.png", 2)
    assert _handler(router, "/foo/value") == 1
    assert _handler(router, "/foo/value.png") == 2


def test_should_throw_when_set_upping_two_parametric_nodes() -> None:
    """should throw when set upping two parametric nodes"""
    router = Router[int]()
    router.on("GET", "/foo/:bar", 1)
    with pytest.raises(ValueError, match="already declared"):
        router.on("GET", "/foo/:baz", 2)


def test_should_throw_when_set_upping_two_regexp_nodes() -> None:
    """should throw when set upping two regexp nodes"""
    router = Router[int]()
    router.on("GET", "/foo/:bar(123)", 1)
    with pytest.raises(ValueError, match="already declared"):
        router.on("GET", "/foo/:bar(456)", 2)


def test_should_set_up_two_parametric_nodes_with_static_ending() -> None:
    """should set up two parametric nodes with static ending"""
    router = Router[int]()
    router.on("GET", "/foo/:bar.png", 1)
    router.on("GET", "/foo/:bar.jpeg", 2)
    assert _handler(router, "/foo/value.png") == 1
    assert _handler(router, "/foo/value.jpeg") == 2


def test_should_set_up_two_regexp_nodes_with_static_ending() -> None:
    """should set up two regexp nodes with static ending"""
    router = Router[int]()
    router.on("GET", "/foo/:bar(123).png", 1)
    router.on("GET", "/foo/:bar(456).jpeg", 2)
    assert _handler(router, "/foo/123.png") == 1
    assert _handler(router, "/foo/456.jpeg") == 2


def test_node_with_longer_static_suffix_should_have_higher_priority() -> None:
    """node with longer static suffix should have higher priority"""
    router = Router[int]()
    router.on("GET", "/foo/:bar.png", 1)
    router.on("GET", "/foo/:bar.png.png", 2)
    assert _handler(router, "/foo/value.png") == 1
    assert _handler(router, "/foo/value.png.png") == 2


def test_node_with_longer_static_suffix_should_have_higher_priority_reversed() -> None:
    """node with longer static suffix should have higher priority when registered first"""
    router = Router[int]()
    router.on("GET", "/foo/:bar.png.png", 2)
    router.on("GET", "/foo/:bar.png", 1)
    assert _handler(router, "/foo/value.png") == 1
    assert _handler(router, "/foo/value.png.png") == 2


def test_should_set_up_regexp_node_and_node_with_static_ending() -> None:
    """should set up regexp node and node with static ending"""
    router = Router[int]()
    router.on("GET", "/foo/:bar(123)", 1)
    router.on("GET", "/foo/:bar(123).jpeg", 2)
    assert _handler(router, "/foo/123") == 1
    assert _handler(router, "/foo/123.jpeg") == 2


def test_distinguishes_routes_with_different_static_parts_between_parameters() -> None:
    """distinguishes routes with different static parts between parameters"""
    router = Router[str]()
    router.on("GET", "/foo/:a-:b", "dash")
    router.on("GET", "/foo/:a.:b", "dot")
    assert _handler(router, "/foo/x-y") == "dash"
    assert _handler(router, "/foo/x.y") == "dot"


# --- path params match ------------------------------------------------------------------


def test_path_params_match() -> None:
    """path params match"""
    router = Router[int | str]()
    router.on("GET", "/ab1", 1)
    router.on("GET", "/ab2", 2)
    router.on("GET", "/ac", "c")
    router.on("GET", "/:pam", "param")
    for base, expected in (("ab1", 1), ("ab2", 2), ("ac", "c"), ("foo", "param")):
        for path in (f"/{base}", f"/{base}/", f"//{base}", f"//{base}//"):
            assert _handler(router, path) == expected
    for path in ("/abcdef", "/abcdef/", "//abcdef"):
        assert router.find("GET", path) == FindResult("param", {"pam": "abcdef"}, {})


# --- querystring ---------------------------------------------------------------------


def _search(path: str) -> object:
    router = Router[bool]()
    router.on("GET", "/test", True)
    result = router.find("GET", path)
    return None if result is None else result.search_params


def test_should_sanitize_the_url_query() -> None:
    """should sanitize the url - query"""
    assert _search("/test?hello=world") == {"hello": "world"}


def test_should_sanitize_the_url_hash() -> None:
    """should sanitize the url - hash"""
    assert _search("/test#hello") == {"hello": ""}


def test_handles_path_and_query_separated_by_semicolon() -> None:
    """handles path and query separated by ;"""
    assert _search("/test;jsessionid=123456") == {"jsessionid": "123456"}


def test_handles_percent() -> None:
    """handles %"""
    assert _search("/test?%") == {"%": ""}


def test_normalizes_duplicate_path_slashes_without_changing_query_slashes() -> None:
    """normalizes duplicate path slashes without changing query slashes"""
    router = Router[bool]()
    router.on("GET", "/user/:id", True)
    result = router.find("GET", "//user//1?u=https://x.com/y")
    assert result is not None
    assert result.params == {"id": "1"}
    assert result.search_params == {"u": "https://x.com/y"}


def test_decodes_percent_heavy_parameters_exactly_once_without_changing_query_boundaries() -> None:
    """decodes percent-heavy parameters exactly once without changing query boundaries"""
    router = Router[bool](RouterConfig(max_param_length=200_000))
    router.on("GET", "/test/:id", True)
    encoded = "%25" * 50_000 + "%252F%2f%C3%A9%20%25"
    decoded = "%" * 50_000 + "%2F/é %"
    for delimiter in ("?", "#", ";"):
        result = router.find("GET", "/test/" + encoded + delimiter + "value=%2525")
        assert result is not None
        assert result.handler is True
        assert result.params == {"id": decoded}
        assert result.search_params == {"value": "%25"}
    found = router.find("GET", "/test/" + encoded)
    assert found is not None
    assert found.params == {"id": decoded}
    assert router.find("GET", "/test/" + encoded + "%zz") is None


def test_keeps_semicolon_in_the_path_when_use_semicolon_delimiter_is_false() -> None:
    """keeps ; in the path when useSemicolonDelimiter is false"""
    router = Router[str](RouterConfig(use_semicolon_delimiter=False))
    router.on("GET", "/test", "static")
    router.on("GET", "/test/:id", "param")
    assert router.find("GET", "/test;jsessionid=123456") is None
    assert router.find("GET", "/test/a;v=1?x=1;y=2") == FindResult(
        "param", {"id": "a;v=1"}, {"x": "1;y=2"}
    )


def _find_literal(route: str, url: str) -> FindResult[bool] | None:
    router = Router[bool](RouterConfig(decode_static_path=False, max_param_length=8))
    router.on("GET", route, True)
    return router.find("GET", url)


def test_matches_static_segments_literally_when_decode_static_path_is_false() -> None:
    """matches static segments literally when decodeStaticPath is false"""
    for route, url in [
        ("/internal/signing/submit", "/internal/%73igning/submit"),
        ("/internal/keys/:id", "/internal/%6Beys/abc"),
        ("/internal/:a/keys/:b", "/internal/x/%6Beys/y"),
        ("/files/*", "/%66iles/a"),
        ("/files/:name.png", "/%66iles/a.png"),
        ("/files/pre-:name.png", "/files/%70re-a.png"),
        ("/files/pre-:name", "/files/pre%2Dx"),
        ("/files/pre*", "/files/%70rex"),
        ("/caf%C3%A9", "/caf%25C3%25A9"),
        ("/café", "/caf%C3%A9"),
    ]:
        assert _find_literal(route, url) is None, url
    assert _find_literal("/internal/signing/submit", "/internal/signing/submit") is not None
    assert _find_literal("/caf%C3%A9", "/caf%C3%A9") is not None
    assert _find_literal("/caf%C3%A9", "/caf%c3%a9") is not None


def test_decodes_parameters_once_when_decode_static_path_is_false() -> None:
    """decodes parameters once when decodeStaticPath is false"""
    assert _params(_find_literal("/keys/:id", "/keys/a%2Fb%20caf%C3%A9")) == {"id": "a/b café"}
    assert _params(_find_literal("/keys/:id", "/keys/%252f")) == {"id": "%2f"}
    assert _params(_find_literal("/a/:a/b/:b", "/a/x%20y/b/c%2Fd")) == {"a": "x y", "b": "c/d"}
    assert _params(_find_literal("/files/*", "/files/a%2Fb/c%20d")) == {"*": "a/b/c d"}
    assert _params(_find_literal("/files/:name.png", "/files/a%2Epng")) == {"name": "a"}
    assert _params(_find_literal("/files/pre-:name.png", "/files/pre-a%2Epng")) == {"name": "a"}
    assert _params(_find_literal("/files/pre*", "/files/prex%2Fy")) == {"*": "x/y"}
    assert _params(_find_literal(r"/n/:id(^\d+$)", "/n/%31%32")) == {"id": "12"}
    assert _find_literal("/slugs/:slug([^.]+)", "/slugs/a%2Eb") is None


def test_applies_max_param_length_to_decoded_parameters_when_decode_static_path_is_false() -> None:
    """applies maxParamLength to decoded parameters when decodeStaticPath is false"""
    eight = "%41%42%43%44%45%46%47%48"
    assert _params(_find_literal("/keys/:id", "/keys/" + eight)) == {"id": "ABCDEFGH"}
    assert _find_literal("/keys/:id", "/keys/" + eight + "%49") is None
    assert _params(_find_literal(r"/n/:id(^\w+$)", "/n/" + eight)) == {"id": "ABCDEFGH"}
    assert _find_literal(r"/n/:id(^\w+$)", "/n/" + eight + "%49") is None


def test_treats_malformed_escapes_in_parameters_as_a_miss_when_decode_static_path_is_false() -> (
    None
):
    """treats malformed escapes in parameters as a miss when decodeStaticPath is false"""
    for route, url in [
        ("/keys/:id", "/keys/%zz"),
        ("/keys/:id", "/keys/%C3"),
        ("/files/*", "/files/a/%zz"),
    ]:
        assert _find_literal(route, url) is None, url
    # A literal % before the parameter is route text, not part of the decoded value.
    assert _params(_find_literal("/files/100%:id", "/files/100%a")) == {"id": "a"}
    assert _find_literal("/files/100%:id", "/files/100%%zz") is None

    router = Router[str](RouterConfig(decode_static_path=False))
    router.on("GET", "/en/:page", "page")
    router.on("GET", "/:lang/100%", "percent")
    assert _params(router.find("GET", "/en/100%")) == {"lang": "en"}


def test_applies_each_path_option_independently() -> None:
    """applies each path option independently"""
    literal = Router[bool](RouterConfig(decode_static_path=False))
    literal.on("GET", "/internal/signing", True)
    assert literal.find("GET", "/INTERNAL//signing/;v=1") is not None
    assert literal.find("GET", "/internal/%73igning") is None

    semicolon = Router[bool](RouterConfig(use_semicolon_delimiter=False))
    semicolon.on("GET", "/internal/signing", True)
    assert semicolon.find("GET", "/INTERNAL//%73igning/") is not None
    assert semicolon.find("GET", "/internal/signing;v=1") is None

    # Effect passes ``undefined`` for both options; a dataclass field has its default.
    defaults = Router[bool](RouterConfig())
    defaults.on("GET", "/internal/signing", True)
    assert defaults.find("GET", "/internal/%73igning;v=1") is not None


def test_strict_config_only_matches_the_registered_path() -> None:
    """strictConfig only matches the registered path"""
    router = Router[bool](strict_config)
    router.on("GET", "/internal/signing/submit", True)
    router.on("GET", "/caf%C3%A9", True)
    assert router.find("GET", "/internal/signing/submit?x=1") is not None
    assert router.find("GET", "/caf%C3%A9") is not None
    for url in [
        "/internal/SIGNING/submit",
        "/internal//signing/submit",
        "/internal/signing/submit/",
        "/internal/%73igning/submit",
        "/internal/signing/submit;v=1",
        "/caf%c3%a9",
    ]:
        assert router.find("GET", url) is None, url


# --- regex ---------------------------------------------------------------------------


def test_route_with_matching_regex() -> None:
    """route with matching regex"""
    router = Router[bool]()
    router.on("GET", r"/test/:id(^\d+$)", True)
    assert _handler(router, "/test/12") is True


def test_route_without_matching_regex() -> None:
    """route without matching regex"""
    router = Router[bool]()
    router.on("GET", r"/test/:id(^\d+$)", True)
    assert router.find("GET", "/test/test") is None


def test_route_with_an_extension_regex_2() -> None:
    """route with an extension regex 2"""
    router = Router[int]()
    router.on("GET", r"/test/S/:file(^\S+).png", 1)
    router.on("GET", r"/test/D/:file(^\D+).png", 2)
    assert _handler(router, "/test/S/foo.png") == 1
    assert _handler(router, "/test/D/foo.png") == 2


def test_nested_route_with_matching_regex() -> None:
    """nested route with matching regex"""
    router = Router[bool]()
    router.on("GET", r"/test/:id(^\d+$)/hello", True)
    assert _handler(router, "/test/12/hello") is True


def test_mixed_nested_route_with_matching_regex() -> None:
    """mixed nested route with matching regex"""
    router = Router[bool]()
    router.on("GET", r"/test/:id(^\d+$)/hello/:world", True)
    assert _params(router.find("GET", "/test/12/hello/world")) == {"id": "12", "world": "world"}


def test_mixed_nested_route_with_double_matching_regex() -> None:
    """mixed nested route with double matching regex"""
    router = Router[bool]()
    router.on("GET", r"/test/:id(^\d+$)/hello/:world(^\d+$)", True)
    assert _params(router.find("GET", "/test/12/hello/15")) == {"id": "12", "world": "15"}


def test_mixed_nested_route_without_double_matching_regex() -> None:
    """mixed nested route without double matching regex"""
    router = Router[bool]()
    router.on("GET", r"/test/:id(^\d+$)/hello/:world(^\d+$)", True)
    assert router.find("GET", "/test/12/hello/test") is None


def test_route_with_an_extension_regex() -> None:
    """route with an extension regex"""
    router = Router[bool]()
    router.on("GET", r"/test/:file(^\d+).png", True)
    assert _handler(router, "/test/12.png") is True


def test_route_with_an_extension_regex_no_match() -> None:
    """route with an extension regex - no match"""
    router = Router[bool]()
    router.on("GET", r"/test/:file(^\d+).png", True)
    assert router.find("GET", "/test/aa.png") is None


def test_safe_decode_uri_component() -> None:
    """safe decodeURIComponent"""
    router = Router[bool]()
    router.on("GET", r"/test/:id(^\d+$)", True)
    assert router.find("GET", '/test/hel%"Flo') is None


def test_rejects_truncated_percent_encodings() -> None:
    """rejects truncated percent encodings"""
    router = Router[bool]()
    router.on("GET", "/test/:id", True)
    assert router.find("GET", "/test/a%") is None
    assert router.find("GET", "/test/a%2") is None


def test_does_not_match_an_empty_segment_against_a_non_empty_regex() -> None:
    """does not match an empty segment against a non-empty regex"""
    router = Router[bool](RouterConfig(ignore_trailing_slash=False))
    router.on("GET", r"/users/:userId(^\d+)", True)
    assert router.find("GET", "/users/") is None


def test_matches_undefined_regex_captures_as_empty_strings() -> None:
    """matches undefined regex captures as empty strings"""
    router = Router[bool](RouterConfig(ignore_trailing_slash=False))
    router.on("GET", "/test/:id(^((?!abc).)*$)", True)
    assert _params(router.find("GET", "/test/")) == {"id": ""}


def test_falls_back_when_a_parameter_exceeds_max_param_length() -> None:
    """falls back when a parameter exceeds maxParamLength"""
    router = Router[str](RouterConfig(max_param_length=3))
    router.on("GET", "/users/:userId", "parameter")
    router.on("GET", "/users/*", "wildcard")
    assert _handler(router, "/users/long") == "wildcard"


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("avoids backtracking across static parameter separators", ("-", "a")),
        ("avoids backtracking across mixed static parameter separators", ("a-", "b")),
    ],
)
def test_avoids_backtracking(name: str, path: tuple[str, str]) -> None:
    """$name"""
    del name
    router = Router[bool]()
    router.on("GET", "/:foo-:bar-", True)
    run, end = path

    def finding(size: int) -> Callable[[], object]:
        long_path = "/" + run * size + end
        return lambda: router.find("GET", long_path)

    assert_near_linear(finding, 1000)
