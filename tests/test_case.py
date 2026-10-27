"""Case conversion on inputs Effect's tests leave out, each result printed
by Effect's ``String`` case functions under Node: acronyms, digits,
non-ASCII letters (never word characters), separator runs."""

import pytest

from pyfect import case

CASES = {
    "XMLHttpRequest": ("xmlHttpRequest", "XmlHttpRequest", "xml_http_request", "XML_HTTP_REQUEST"),
    "MyURLParser2Go": (
        "myUrlParser2Go",
        "MyUrlParser2Go",
        "my_url_parser_2_go",
        "MY_URL_PARSER2_GO",
    ),
    "foo  bar__baz--qux": ("fooBarBazQux", "FooBarBazQux", "foo_bar_baz_qux", "FOO_BAR_BAZ_QUX"),
    "Ünicode_wörd": ("nicodeWRd", "NicodeWRd", "nicode_w_rd", "NICODE_W_RD"),
    "a1B2c3": ("a1B2C3", "A1B2C3", "a_1_b_2_c_3", "A1_B2C3"),
    "___": ("", "", "", ""),
}


@pytest.mark.parametrize("text", list(CASES))
def test_word_converters_match_effect(text: str):
    camel, pascal, snake, config = CASES[text]
    assert case.camel_case(text) == camel
    assert case.pascal_case(text) == pascal
    assert case.snake_case(text) == snake
    assert case.config_case(text) == config


@pytest.mark.parametrize(
    ("text", "camel", "pascal"),
    [("___", "__", "__"), ("_foo", "_foo", "_foo"), ("a__b", "a_b", "A_b"), ("x_ä", "xÄ", "XÄ")],
)
def test_snake_converters_match_effect(text: str, camel: str, pascal: str):
    assert case.snake_to_camel(text) == camel
    assert case.snake_to_pascal(text) == pascal
