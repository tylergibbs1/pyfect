"""Ports of the case-function tests of Effect's ``String.test.ts``
(``pyfect.case``). Each test's docstring is the Effect test title, prefixed
by its ``describe`` block.

The rest of ``String.test.ts`` is Python's ``str`` and is not ported.
Within ``noCase``: ``data-last with options`` is a keyword call (the module
has no curried form), and the ``transform`` callback takes the word only.
"""

import re

from pyfect import case


def test_snake_to_camel_converts_snake_case_to_camel_case() -> None:
    """snakeToCamel: converts snake_case to camelCase"""
    assert case.snake_to_camel("hello_world") == "helloWorld"
    assert case.snake_to_camel("foo_bar_baz") == "fooBarBaz"


def test_snake_to_camel_handles_single_word() -> None:
    """snakeToCamel: handles single word"""
    assert case.snake_to_camel("hello") == "hello"


def test_snake_to_camel_handles_an_empty_string() -> None:
    """snakeToCamel: handles an empty string"""
    assert case.snake_to_camel("") == ""


def test_snake_to_camel_handles_trailing_and_separator_only_inputs() -> None:
    """snakeToCamel: handles trailing and separator-only inputs"""
    assert case.snake_to_camel("foo_") == "foo"
    assert case.snake_to_camel("__") == ""


def test_snake_to_pascal_converts_snake_case_to_pascal_case() -> None:
    """snakeToPascal: converts snake_case to PascalCase"""
    assert case.snake_to_pascal("hello_world") == "HelloWorld"
    assert case.snake_to_pascal("foo_bar_baz") == "FooBarBaz"


def test_snake_to_pascal_handles_an_empty_string() -> None:
    """snakeToPascal: handles an empty string"""
    assert case.snake_to_pascal("") == ""


def test_snake_to_pascal_handles_trailing_and_separator_only_inputs() -> None:
    """snakeToPascal: handles trailing and separator-only inputs"""
    assert case.snake_to_pascal("foo_") == "Foo"
    assert case.snake_to_pascal("__") == ""


def test_snake_to_kebab_converts_snake_case_to_kebab_case() -> None:
    """snakeToKebab: converts snake_case to kebab-case"""
    assert case.snake_to_kebab("hello_world") == "hello-world"
    assert case.snake_to_kebab("foo_bar_baz") == "foo-bar-baz"


def test_snake_to_kebab_keeps_digits_and_edge_separators() -> None:
    """snakeToKebab: keeps digits and edge separators"""
    assert case.snake_to_kebab("v2_api") == "v2-api"
    assert case.snake_to_kebab("foo_") == "foo-"


def test_camel_to_snake_converts_camel_case_to_snake_case() -> None:
    """camelToSnake: converts camelCase to snake_case"""
    assert case.camel_to_snake("helloWorld") == "hello_world"
    assert case.camel_to_snake("fooBarBaz") == "foo_bar_baz"


def test_camel_to_snake_splits_every_capital_and_keeps_separators() -> None:
    """camelToSnake: splits every capital and keeps separators"""
    assert case.camel_to_snake("XMLHttpRequest") == "_x_m_l_http_request"
    assert case.camel_to_snake("xmlHTTPResponse") == "xml_h_t_t_p_response"
    assert case.camel_to_snake("field2Value") == "field2_value"
    assert case.camel_to_snake("foo_") == "foo_"


def test_pascal_to_snake_converts_pascal_case_to_snake_case() -> None:
    """pascalToSnake: converts PascalCase to snake_case"""
    assert case.pascal_to_snake("HelloWorld") == "hello_world"
    assert case.pascal_to_snake("FooBarBaz") == "foo_bar_baz"


def test_pascal_to_snake_splits_every_capital() -> None:
    """pascalToSnake: splits every capital"""
    assert case.pascal_to_snake("XMLHttpRequest") == "x_m_l_http_request"
    assert case.pascal_to_snake("field2Value") == "field2_value"


def test_kebab_to_snake_converts_kebab_case_to_snake_case() -> None:
    """kebabToSnake: converts kebab-case to snake_case"""
    assert case.kebab_to_snake("hello-world") == "hello_world"
    assert case.kebab_to_snake("foo-bar-baz") == "foo_bar_baz"


def test_kebab_to_snake_keeps_repeated_and_edge_separators() -> None:
    """kebabToSnake: keeps repeated and edge separators"""
    assert case.kebab_to_snake("--foo--") == "__foo__"


def test_no_case_converts_to_space_separated_lowercase_by_default() -> None:
    """noCase: converts to space-separated lowercase by default"""
    assert case.no_case("helloWorld") == "hello world"
    assert case.no_case("HelloWorld") == "hello world"


def test_no_case_data_last_with_options() -> None:
    """noCase: data-last with options"""
    assert case.no_case("helloWorld", delimiter="-") == "hello-world"


def test_no_case_uses_a_custom_split_regular_expression() -> None:
    """noCase: uses a custom split regular expression"""
    assert case.no_case("ab", split=re.compile(r"([a])([b])")) == "a b"


def test_no_case_uses_custom_split_regular_expressions() -> None:
    """noCase: uses custom split regular expressions"""
    split = [re.compile(r"([a])([b])"), re.compile(r"([b])([c])")]
    assert case.no_case("abc", split=split) == "a b c"


def test_no_case_uses_a_custom_strip_regular_expression() -> None:
    """noCase: uses a custom strip regular expression"""
    assert case.no_case("a_b-c", strip=re.compile("_")) == "a b-c"


def test_no_case_uses_custom_strip_regular_expressions() -> None:
    """noCase: uses custom strip regular expressions"""
    assert case.no_case("a_b-c", strip=[re.compile("_"), re.compile("-")]) == "a b c"


def test_no_case_handles_underscores_and_hyphens() -> None:
    """noCase: handles underscores and hyphens"""
    assert case.no_case("hello_world") == "hello world"
    assert case.no_case("hello-world") == "hello world"


def test_no_case_splits_digit_letter_boundaries() -> None:
    """noCase: splits digit-letter boundaries"""
    assert case.no_case("field2value") == "field 2 value"
    assert case.no_case("field2Value") == "field 2 value"


def test_no_case_does_not_transform_a_word_for_inputs_without_words() -> None:
    """noCase: does not transform a word for inputs without words"""
    parts: list[str] = []

    def transform(part: str) -> str:
        parts.append(part)
        return part

    assert case.no_case("", transform=transform) == ""
    assert case.no_case("---", transform=transform) == ""
    assert parts == []


def test_pascal_case_converts_to_pascal_case() -> None:
    """pascalCase: converts to PascalCase"""
    assert case.pascal_case("hello world") == "HelloWorld"
    assert case.pascal_case("hello_world") == "HelloWorld"
    assert case.pascal_case("helloWorld") == "HelloWorld"


def test_pascal_case_does_not_prefix_numeric_segments_with_underscores() -> None:
    """pascalCase: does not prefix numeric segments with underscores"""
    assert case.pascal_case("foo 2 bar") == "Foo2Bar"
    assert case.pascal_case("api-v2 xml") == "ApiV2Xml"


def test_camel_case_converts_to_camel_case() -> None:
    """camelCase: converts to camelCase"""
    assert case.camel_case("hello world") == "helloWorld"
    assert case.camel_case("hello_world") == "helloWorld"
    assert case.camel_case("HelloWorld") == "helloWorld"


def test_camel_case_does_not_prefix_numeric_segments_with_underscores() -> None:
    """camelCase: does not prefix numeric segments with underscores"""
    assert case.camel_case("foo 2 bar") == "foo2Bar"
    assert case.camel_case("api-v2 xml") == "apiV2Xml"


def test_constant_case_converts_to_constant_case() -> None:
    """constantCase: converts to CONSTANT_CASE"""
    assert case.constant_case("hello world") == "HELLO_WORLD"
    assert case.constant_case("helloWorld") == "HELLO_WORLD"
    assert case.constant_case("api-v2 xml") == "API_V_2_XML"


def test_config_case_converts_to_config_case() -> None:
    """configCase: converts to CONFIG_CASE"""
    assert case.config_case("hello world") == "HELLO_WORLD"
    assert case.config_case("helloWorld") == "HELLO_WORLD"
    assert case.config_case("api-v2 xml") == "API_V2_XML"
    assert case.config_case("field2Value") == "FIELD2_VALUE"


def test_config_case_is_not_idempotent() -> None:
    """configCase: is not idempotent"""
    assert case.config_case("field2value") == "FIELD2VALUE"
    assert case.config_case("FIELD2VALUE") == "FIELD2_VALUE"


def test_kebab_case_converts_to_kebab_case() -> None:
    """kebabCase: converts to kebab-case"""
    assert case.kebab_case("hello world") == "hello-world"
    assert case.kebab_case("helloWorld") == "hello-world"


def test_snake_case_converts_to_snake_case() -> None:
    """snakeCase: converts to snake_case"""
    assert case.snake_case("hello world") == "hello_world"
    assert case.snake_case("helloWorld") == "hello_world"
