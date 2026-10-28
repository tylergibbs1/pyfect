"""Ports of Effect's ``ConfigProvider.test.ts``.

Each test's docstring is the Effect test title. Effect's ``fromDotEnv`` and
``fromDir`` tests mock the ``FileSystem`` service with ``layerNoop``; here
they subclass ``NoopFileSystem``.
"""

from collections.abc import Callable

import pyfect as fx
from pyfect import config_provider as cp
from pyfect import file_system, layer, testing
from pyfect.config_provider import Array, Record, SourceError, Value
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.path import layer_posix as path_layer_posix
from pyfect.platform_error import PlatformError, system_error


def _load(
    provider: cp.ConfigProvider, path: cp.PathInput
) -> fx.Ok[cp.Node | None] | fx.Err[SourceError]:
    return fx.run_sync(provider.load(path).result())


def assert_success(provider: cp.ConfigProvider, path: cp.PathInput, expected: cp.Node) -> None:
    assert _load(provider, path) == fx.Ok(expected)


def assert_missing(provider: cp.ConfigProvider, path: cp.PathInput) -> None:
    assert _load(provider, path) == fx.Ok(None)


def assert_failure(provider: cp.ConfigProvider, path: cp.PathInput, expected: SourceError) -> None:
    assert _load(provider, path) == fx.Err(expected)


def keys(*names: str) -> frozenset[str]:
    return frozenset(names)


# --- make ----------------------------------------------------------------------


@testing.effect
def test_exposes_lookup_absence_and_input_transformation_as_provider_behavior():
    """exposes lookup absence and input transformation as provider behavior"""
    provider = cp.from_unknown({"APP": {"PORT": "3000"}})
    nested = provider.map_input(lambda path: ("APP", *path))

    assert (yield from nested.load(["PORT"]).result()) == fx.Ok(Value("3000"))
    assert (yield from nested.load(["MISSING"]).result()) == fx.Ok(None)


def test_creates_a_provider_from_a_lookup_function():
    """creates a provider from a lookup function"""
    provider = cp.make(
        lambda path: fx.succeed(Value("value") if ".".join(map(str, path)) == "A.B" else None)
    )

    assert_success(provider, ["A", "B"], Value("value"))
    assert_missing(provider, ["missing"])


def test_preserves_source_error_failures():
    """preserves SourceError failures"""
    error = SourceError("source unavailable")
    provider = cp.make(lambda _: fx.fail(error))

    assert_failure(provider, ["A"], error)


# --- combinators: or_else --------------------------------------------------------


def test_uses_the_fallback_when_the_primary_provider_is_missing_the_path():
    """uses the fallback when the primary provider is missing the path"""
    primary = cp.from_env(env={"A": "value1"})
    fallback = cp.from_env(env={"B": "value2"})
    provider = primary.or_else(fallback)
    assert_success(provider, ["A"], Value("value1"))
    assert_success(provider, ["B"], Value("value2"))


def test_does_not_use_the_fallback_after_a_source_error():
    """does not use the fallback after a SourceError"""
    error = SourceError("io down")
    primary = cp.make(lambda _: fx.fail(error))
    fallback = cp.from_env(env={"KEY": "fallback"})
    provider = primary.or_else(fallback)
    assert_failure(provider, ["KEY"], error)


def test_does_not_evaluate_the_fallback_after_the_primary_provider_finds_a_node():
    """does not evaluate the fallback after the primary provider finds a node"""
    primary = cp.from_unknown({"KEY": "primary"})
    fallback = cp.make(lambda _: fx.fail(SourceError("fallback evaluated")))
    provider = primary.or_else(fallback)

    assert_success(provider, ["KEY"], Value("primary"))


def test_preserves_each_operands_transformations():
    """preserves each operand's transformations"""
    primary = cp.from_env(env={"DATABASE_HOST": "from-env"}).constant_case()
    fallback = cp.from_env(env={"APP_PORT": "3000"}).nested("APP")
    provider = primary.or_else(fallback)
    assert_success(provider, ["databaseHost"], Value("from-env"))
    assert_success(provider, ["PORT"], Value("3000"))


def test_distributes_map_input_over_both_operands():
    """distributes mapInput over both operands"""

    def append_suffix(path: cp.Path) -> cp.Path:
        return tuple(f"{seg}_SUFFIX" if isinstance(seg, str) else seg for seg in path)

    primary = cp.from_env(env={"prefix_SUFFIX_KEY_SUFFIX": "primary"}).nested("prefix")
    fallback = cp.from_env(
        env={"fallback_SUFFIX_KEY_SUFFIX": "fallback", "fallback_SUFFIX_OTHER_SUFFIX": "fallback"}
    ).nested("fallback")
    provider = primary.or_else(fallback).map_input(append_suffix)
    assert_success(provider, ["KEY"], Value("primary"))
    assert_success(provider, ["OTHER"], Value("fallback"))


def test_distributes_nested_over_both_operands():
    """distributes nested over both operands"""
    primary = cp.from_env(env={"app_DATABASE_HOST": "primary"}).constant_case()
    fallback = cp.from_env(env={"app_PORT": "fallback"})
    provider = primary.or_else(fallback).nested("app")
    assert_success(provider, ["databaseHost"], Value("primary"))
    assert_success(provider, ["PORT"], Value("fallback"))


def test_uses_the_fallback_when_the_primary_value_is_an_empty_string():
    """uses the fallback when the primary value is an empty string"""
    primary = cp.from_env(env={"KEY": ""})
    fallback = cp.from_unknown({"KEY": "fallback"})
    provider = primary.or_else(fallback)
    assert_success(provider, ["KEY"], Value("fallback"))


def test_does_not_merge_a_fallback_container_into_an_existing_primary_container():
    """does not merge a fallback container into an existing primary container"""
    primary = cp.from_unknown({"primary": "value1"})
    fallback = cp.from_unknown({"fallback": "value2"})
    provider = primary.or_else(fallback)

    assert_success(provider, [], Record(keys("primary")))
    assert_success(provider, ["fallback"], Value("value2"))


# --- combinators: map_input, constant_case, nested -------------------------------


def _append(suffix: str):
    def f(path: cp.Path) -> cp.Path:
        return tuple(seg + suffix if isinstance(seg, str) else seg for seg in path)

    return f


def test_composes_transformations_in_application_order():
    """composes transformations in application order"""
    provider = (
        cp.from_env(env={"KEY_A_B": "value"}).map_input(_append("_A")).map_input(_append("_B"))
    )
    assert_success(provider, ["KEY"], Value("value"))


def test_converts_string_path_segments_to_config_case():
    """converts string path segments to config case"""
    provider = cp.from_env(env={"CONSTANT_CASE": "value1"}).constant_case()
    assert_success(provider, ["constant.case"], Value("value1"))


def test_preserves_numeric_word_groups():
    """preserves numeric word groups"""
    provider = cp.from_env(env={"API_V2_XML": "value1", "FIELD2_VALUE": "value2"}).constant_case()
    assert_success(provider, ["api-v2 xml"], Value("value1"))
    assert_success(provider, ["field2Value"], Value("value2"))


def test_leaves_numeric_path_segments_unchanged():
    """leaves numeric path segments unchanged"""
    provider = cp.from_unknown({"ITEMS": ["value"]}).constant_case()

    assert_success(provider, ["items", 0], Value("value"))


def test_adds_a_string_prefix_to_the_path():
    """adds a string prefix to the path"""
    provider = cp.from_env(env={"prefix_A": "value"}).nested("prefix")
    assert_success(provider, ["A"], Value("value"))


def test_adds_a_path_prefix_with_string_and_numeric_segments():
    """adds a Path prefix with string and numeric segments"""
    provider = cp.from_unknown({"apps": [{"PORT": "3000"}]}).nested(["apps", 0])

    assert_success(provider, ["PORT"], Value("3000"))


def test_preserves_order_when_constant_case_is_applied_before_nested():
    """preserves order when constantCase is applied before nested"""
    provider = cp.from_env(env={"prefix_KEY_WITH_DOTS": "value"}).constant_case().nested("prefix")
    assert_success(provider, ["key.with.dots"], Value("value"))


def test_preserves_order_when_constant_case_is_applied_after_nested():
    """preserves order when constantCase is applied after nested"""
    provider = (
        cp.from_env(env={"PREFIX_WITH_DOTS_KEY_WITH_DOTS": "value"})
        .nested("prefix.with.dots")
        .constant_case()
    )
    assert_success(provider, ["key.with.dots"], Value("value"))


def test_composes_multiple_prefixes_as_wrappers():
    """composes multiple prefixes as wrappers"""
    provider = cp.from_env(env={"b_a_KEY": "value"}).nested("a").nested("b")
    assert_success(provider, ["KEY"], Value("value"))


def test_allows_a_later_map_input_to_transform_the_prefixed_path():
    """allows a later mapInput to transform the prefixed path"""
    provider = (
        cp.from_env(env={"app_KEY_leaf": "value"})
        .nested("app")
        .map_input(lambda path: (*path, "leaf"))
    )
    assert_success(provider, ["KEY"], Value("value"))


# --- from_env_record --------------------------------------------------------------


def test_reads_defined_values_and_skips_undefined_values():
    """reads defined values and skips undefined values"""
    provider = cp.from_env_record({"DEFINED": "value", "UNDEFINED": None})

    assert_success(provider, ["DEFINED"], Value("value"))
    assert_missing(provider, ["UNDEFINED"])
    assert_success(provider, [], Record(keys("DEFINED")))


def test_treats_empty_strings_as_missing_by_default():
    """treats empty strings as missing by default"""
    assert_missing(cp.from_env_record({"EMPTY": ""}), ["EMPTY"])


def test_from_env_record_preserves_empty_strings_when_requested():
    """preserves empty strings when requested"""
    provider = cp.from_env_record({"EMPTY": ""}, preserve_empty_strings=True)

    assert_success(provider, ["EMPTY"], Value(""))


# --- from_env ----------------------------------------------------------------------


def test_env_without_an_underscore():
    """env without an underscore"""
    provider = cp.from_env(env={"A": "value1"})
    assert_success(provider, ["A"], Value("value1"))


def test_missing_key_returns_none():
    """missing key returns None"""
    provider = cp.from_env(env={"A": "value1"})
    assert_missing(provider, ["missing"])


def test_does_not_read_inherited_environment_properties():
    """does not read inherited environment properties"""
    provider = cp.from_env(env={})
    assert_missing(provider, ["constructor"])


def test_does_not_traverse_inherited_trie_properties():
    """does not traverse inherited trie properties"""
    provider = cp.from_env(env={"constructor_X": "value"})
    assert_success(provider, ["constructor", "X"], Value("value"))


def test_treats_empty_string_values_as_missing_while_preserving_structure_by_default():
    """treats empty string values as missing while preserving structure by default"""
    provider = cp.from_env(env={"A": "", "B": "value1"})

    assert_success(provider, [], Record(keys("A", "B")))
    assert_missing(provider, ["A"])
    assert_success(provider, ["B"], Value("value1"))


def test_from_env_preserves_empty_strings_when_requested():
    """preserves empty strings when requested"""
    provider = cp.from_env(env={"A": ""}, preserve_empty_strings=True)

    assert_success(provider, [], Record(keys("A")))
    assert_success(provider, ["A"], Value(""))


def test_treats_empty_co_located_record_values_as_missing_and_preserves_children():
    """treats empty co-located record values as missing and preserves children"""
    provider = cp.from_env(env={"A": "", "A_B": "value1"})

    assert_success(provider, ["A"], Record(keys("B")))
    assert_success(provider, ["A", "B"], Value("value1"))


def test_preserves_empty_co_located_record_values_when_requested():
    """preserves empty co-located record values when requested"""
    provider = cp.from_env(env={"A": "", "A_B": "value1"}, preserve_empty_strings=True)

    assert_success(provider, ["A"], Record(keys("B"), ""))
    assert_success(provider, ["A", "B"], Value("value1"))


def test_treats_empty_co_located_array_values_as_missing_and_preserves_children():
    """treats empty co-located array values as missing and preserves children"""
    provider = cp.from_env(env={"A": "", "A_0": "value1"})

    assert_success(provider, ["A"], Array(1))
    assert_success(provider, ["A", 0], Value("value1"))


def test_preserves_empty_array_children_structurally_while_treating_their_values_as_missing():
    """preserves empty array children structurally while treating their values as missing"""
    provider = cp.from_env(env={"A_0": "", "A_1": "value1"})

    assert_success(provider, ["A"], Array(2))
    assert_missing(provider, ["A", 0])
    assert_success(provider, ["A", 1], Value("value1"))


def test_direct_lookup_of_a_key_containing_underscores():
    """direct lookup of a key containing underscores"""
    provider = cp.from_env(env={"NODE_ENV": "value1"})
    assert_success(provider, ["NODE_ENV"], Value("value1"))


def test_single_underscore_creates_nesting():
    """single underscore creates nesting"""
    provider = cp.from_env(env={"NODE_ENV": "value1"})

    assert_success(provider, ["NODE"], Record(keys("ENV")))
    assert_success(provider, ["NODE", "ENV"], Value("value1"))


def test_prefix_can_be_both_a_value_and_a_container():
    """prefix can be both a value and a container"""
    provider = cp.from_env(env={"NODE": "value1", "NODE_ENV": "value2"})

    assert_success(provider, ["NODE"], Record(keys("ENV"), "value1"))
    assert_success(provider, ["NODE", "ENV"], Value("value2"))
    assert_success(provider, ["NODE_ENV"], Value("value2"))


def test_multiple_nested_children_under_the_same_prefix():
    """multiple nested children under the same prefix"""
    provider = cp.from_env(env={"NODE": "value1", "NODE_ENV": "value2", "NODE_PATH": "value3"})

    assert_success(provider, ["NODE"], Record(keys("ENV", "PATH"), "value1"))
    assert_success(provider, ["NODE", "ENV"], Value("value2"))
    assert_success(provider, ["NODE", "PATH"], Value("value3"))
    assert_success(provider, ["NODE_PATH"], Value("value3"))


def test_nested_depth_greater_than_2_works():
    """nested depth > 2 works"""
    provider = cp.from_env(env={"A_B_C": "value1"})

    assert_success(provider, ["A"], Record(keys("B")))
    assert_success(provider, ["A", "B"], Record(keys("C")))
    assert_success(provider, ["A", "B", "C"], Value("value1"))


def test_array_dense_numeric_children_yield_an_array_node():
    """array: dense numeric children yield an Array node"""
    provider = cp.from_env(env={"A_0": "value1", "A_1": "value2"})

    assert_success(provider, ["A"], Array(2))
    assert_success(provider, ["A", 0], Value("value1"))
    assert_success(provider, ["A", 1], Value("value2"))


def test_array_non_dense_numeric_children_still_yield_an_array_node():
    """array: non-dense numeric children still yield an Array node"""
    provider = cp.from_env(env={"A": "root", "A_0": "value1", "A_2": "value3"})

    assert_success(provider, ["A"], Array(3, "root"))
    assert_success(provider, ["A", 0], Value("value1"))
    assert_missing(provider, ["A", 1])
    assert_success(provider, ["A", 2], Value("value3"))


def test_array_parent_can_have_a_co_located_value():
    """array: parent can have a co-located value"""
    provider = cp.from_env(env={"A": "root", "A_0": "value1", "A_1": "value2"})

    assert_success(provider, ["A"], Array(2, "root"))
    assert_success(provider, ["A", 0], Value("value1"))
    assert_success(provider, ["A", 1], Value("value2"))


def test_mixed_children_numeric_and_non_numeric_yields_record():
    """mixed children (numeric + non-numeric) yields Record"""
    provider = cp.from_env(env={"A_0": "value1", "A_B": "value2"})

    assert_success(provider, ["A"], Record(keys("0", "B")))
    assert_success(provider, ["A", 0], Value("value1"))
    assert_success(provider, ["A", "B"], Value("value2"))


def test_double_underscore_produces_an_empty_segment():
    """double underscore produces an empty segment (no special handling)"""
    provider = cp.from_env(env={"A__B": "value1"})

    assert_success(provider, ["A"], Record(keys("")))
    assert_success(provider, ["A", ""], Record(keys("B")))
    assert_success(provider, ["A", "", "B"], Value("value1"))
    assert_success(provider, ["A__B"], Value("value1"))


def test_empty_segment_node_can_be_both_a_value_and_a_container():
    """empty segment node can be both a value and a container"""
    provider = cp.from_env(env={"A_": "value1", "A__B": "value2"})

    assert_success(provider, ["A", ""], Record(keys("B"), "value1"))
    assert_success(provider, ["A", "", "B"], Value("value2"))


def test_leading_underscore_creates_an_empty_first_segment():
    """leading underscore creates an empty first segment"""
    provider = cp.from_env(env={"_A": "value1"})

    assert_success(provider, [], Record(keys("")))
    assert_success(provider, [""], Record(keys("A")))
    assert_success(provider, ["", "A"], Value("value1"))
    assert_success(provider, ["_A"], Value("value1"))


def test_trailing_underscore_creates_an_empty_last_segment():
    """trailing underscore creates an empty last segment"""
    provider = cp.from_env(env={"A_": "value1"})

    assert_success(provider, ["A"], Record(keys("")))
    assert_success(provider, ["A", ""], Value("value1"))
    assert_success(provider, ["A_"], Value("value1"))


def test_cannot_descend_past_a_leaf():
    """cannot descend past a leaf (A exists, but A_B does not)"""
    provider = cp.from_env(env={"A": "value1"})

    assert_success(provider, ["A"], Value("value1"))
    assert_missing(provider, ["A", "B"])
    assert_missing(provider, ["A_B"])


def test_direct_lookup_and_nested_lookup_both_work_for_the_same_env_var():
    """direct lookup and nested lookup both work for the same env var"""
    provider = cp.from_env(env={"A_B": "value1"})

    assert_success(provider, ["A_B"], Value("value1"))
    assert_success(provider, ["A"], Record(keys("B")))
    assert_success(provider, ["A", "B"], Value("value1"))


def test_prefix_value_is_preserved_when_there_are_multiple_nested_children():
    """prefix value is preserved when there are multiple nested children"""
    provider = cp.from_env(env={"A": "root", "A_B": "value1", "A_C": "value2"})

    assert_success(provider, ["A"], Record(keys("B", "C"), "root"))
    assert_success(provider, ["A", "B"], Value("value1"))
    assert_success(provider, ["A", "C"], Value("value2"))


def test_intermediate_node_can_be_both_a_value_and_a_container():
    """intermediate node can be both a value and a container (A_B and A_B_C)"""
    provider = cp.from_env(env={"A_B": "value1", "A_B_C": "value2"})

    assert_success(provider, ["A_B"], Value("value1"))
    assert_success(provider, ["A"], Record(keys("B")))
    assert_success(provider, ["A", "B"], Record(keys("C"), "value1"))
    assert_success(provider, ["A", "B", "C"], Value("value2"))


def test_numeric_index_string_and_number_segments_should_resolve_the_same():
    """numeric index: string and number segments should resolve the same"""
    provider = cp.from_env(env={"A_0": "value1"})

    assert_success(provider, ["A", 0], Value("value1"))
    assert_success(provider, ["A", "0"], Value("value1"))


def test_array_leading_zero_indices_are_not_numeric_so_it_yields_a_record():
    """array: leading-zero indices are not numeric, so it yields a Record"""
    provider = cp.from_env(env={"A_01": "value1", "A_1": "value2"})

    assert_success(provider, ["A"], Record(keys("01", "1")))
    assert_success(provider, ["A", "01"], Value("value1"))
    assert_success(provider, ["A", 1], Value("value2"))


def test_array_values_outside_the_javascript_array_index_range_yield_a_record():
    """array: values outside the JavaScript array index range yield a Record"""
    provider = cp.from_env(env={"A_4294967295": "value1"})

    assert_success(provider, ["A"], Record(keys("4294967295")))
    assert_success(provider, ["A", "4294967295"], Value("value1"))


def test_root_path_exposes_top_level_keys():
    """root path exposes top-level keys"""
    provider = cp.from_env(env={"A": "value1", "B_C": "value2"})

    assert_success(provider, [], Record(keys("A", "B")))
    assert_success(provider, ["A"], Value("value1"))
    assert_success(provider, ["B"], Record(keys("C")))


def test_underscore_only_key_creates_empty_segments():
    """underscore-only key creates empty segments"""
    provider = cp.from_env(env={"_": "value1"})

    assert_success(provider, ["_"], Value("value1"))
    assert_success(provider, [], Record(keys("")))
    assert_success(provider, [""], Record(keys("")))
    assert_success(provider, ["", ""], Value("value1"))


def test_array_non_integer_indices_do_not_yield_an_array_node():
    """array: non-integer indices do not yield an Array node"""
    provider = cp.from_env(env={"A_-1": "value1", "A_1.5": "value2"})

    assert_success(provider, ["A"], Record(keys("-1", "1.5")))


# --- from_unknown ---------------------------------------------------------------------


class _Symbol:
    def __str__(self) -> str:
        return "Symbol(unknown)"


_UNKNOWN = cp.from_unknown(
    {
        "string": "value1",
        "record": {"key1": "value2", "key2": {"key3": "value3"}},
        "array": ["value4", {"key4": "value5"}, ["value6"]],
        "null": None,
        "number": 42,
        "boolean": True,
        "bigint": 0,
        "undefined": None,
        "unknown": _Symbol(),
    }
)


def test_root_node():
    """Root node"""
    assert_success(
        _UNKNOWN,
        [],
        Record(
            keys(
                "string",
                "record",
                "array",
                "null",
                "number",
                "boolean",
                "bigint",
                "undefined",
                "unknown",
            )
        ),
    )


def test_exact_leaf_resolution():
    """Exact leaf resolution"""
    assert_success(_UNKNOWN, ["string"], Value("value1"))
    assert_success(_UNKNOWN, ["record", "key1"], Value("value2"))
    assert_success(_UNKNOWN, ["array", 0], Value("value4"))
    assert_success(_UNKNOWN, ["array", 1, "key4"], Value("value5"))
    assert_success(_UNKNOWN, ["array", 2, 0], Value("value6"))


def test_treats_empty_string_leaves_as_missing_by_default():
    """treats empty string leaves as missing by default"""
    provider = cp.from_unknown({"a": "", "b": "value1", "record": {"key": ""}, "array": [""]})

    assert_success(provider, [], Record(keys("a", "b", "record", "array")))
    assert_missing(provider, ["a"])
    assert_success(provider, ["b"], Value("value1"))
    assert_success(provider, ["record"], Record(keys("key")))
    assert_missing(provider, ["record", "key"])
    assert_success(provider, ["array"], Array(1))
    assert_missing(provider, ["array", 0])


def test_preserves_empty_string_leaves_when_requested():
    """preserves empty string leaves when requested"""
    provider = cp.from_unknown({"a": "", "array": [""]}, preserve_empty_strings=True)

    assert_success(provider, ["a"], Value(""))
    assert_success(provider, ["array", 0], Value(""))


def test_object_detection():
    """Object detection"""
    assert_success(_UNKNOWN, ["record"], Record(keys("key1", "key2")))
    assert_success(_UNKNOWN, ["record", "key2"], Record(keys("key3")))


def test_array_detection():
    """Array detection"""
    assert_success(_UNKNOWN, ["array"], Array(3))
    assert_success(_UNKNOWN, ["array", 2], Array(1))


def test_should_return_none_on_non_existing_paths():
    """should return None on non-existing paths"""
    assert_missing(_UNKNOWN, ["string", "non-existing"])
    assert_missing(_UNKNOWN, ["record", "non-existing"])
    assert_missing(_UNKNOWN, ["array", 3, "non-existing"])


def test_does_not_read_inherited_object_properties():
    """does not read inherited object properties"""

    class WithDefault(dict[str, str]):
        def __missing__(self, key: str) -> str:
            return "value1"

    provider = cp.from_unknown(WithDefault(own="value2"))

    assert_success(provider, [], Record(keys("own")))
    assert_missing(provider, ["inherited"])
    assert_success(provider, ["own"], Value("value2"))


def test_null_values():
    """null values"""
    assert_missing(_UNKNOWN, ["null"])


def test_number_values():
    """number values"""
    assert_success(_UNKNOWN, ["number"], Value("42"))


def test_boolean_values():
    """boolean values"""
    assert_success(_UNKNOWN, ["boolean"], Value("true"))


def test_bigint_values():
    """bigint values"""
    assert_success(_UNKNOWN, ["bigint"], Value("0"))


def test_undefined_values():
    """undefined values"""
    assert_missing(_UNKNOWN, ["undefined"])


def test_unknown_values():
    """unknown values"""
    assert_success(_UNKNOWN, ["unknown"], Value("Symbol(unknown)"))


# --- from_dot_env_contents ----------------------------------------------------------------


def test_comments_are_ignored():
    """comments are ignored"""
    provider = cp.from_dot_env_contents("""
# comments are ignored
API_URL=https://api.example.com
""")
    assert_success(provider, [], Record(keys("API")))
    assert_success(provider, ["API_URL"], Value("https://api.example.com"))


def test_export_is_allowed():
    """export is allowed"""
    provider = cp.from_dot_env_contents("""
export NODE_ENV=production
""")
    assert_success(provider, [], Record(keys("NODE")))
    assert_success(provider, ["NODE_ENV"], Value("production"))


def test_supports_single_double_and_backtick_quoted_values():
    """supports single, double, and backtick quoted values"""
    provider = cp.from_dot_env_contents("""
SINGLE='value # one'
DOUBLE="line 1\\nline 2"
BACKTICK=`value # two`
""")
    assert_success(provider, ["SINGLE"], Value("value # one"))
    assert_success(provider, ["DOUBLE"], Value("line 1\nline 2"))
    assert_success(provider, ["BACKTICK"], Value("value # two"))


def test_removes_inline_comments_from_unquoted_values():
    """removes inline comments from unquoted values"""
    provider = cp.from_dot_env_contents("VALUE=value # comment")

    assert_success(provider, ["VALUE"], Value("value"))


def test_objects_are_supported():
    """objects are supported"""
    provider = cp.from_dot_env_contents("""
OBJECT_key1=value1
OBJECT_key2=value2
""")
    assert_success(provider, [], Record(keys("OBJECT")))
    assert_success(provider, ["OBJECT"], Record(keys("key1", "key2")))
    assert_success(provider, ["OBJECT", "key1"], Value("value1"))
    assert_success(provider, ["OBJECT", "key2"], Value("value2"))


def test_dot_env_treats_empty_string_values_as_missing_while_preserving_structure_by_default():
    """treats empty string values as missing while preserving structure by default"""
    provider = cp.from_dot_env_contents("""
A=
B=value1
""")
    assert_success(provider, [], Record(keys("A", "B")))
    assert_missing(provider, ["A"])
    assert_success(provider, ["B"], Value("value1"))


def test_dot_env_preserves_empty_strings_when_requested():
    """preserves empty strings when requested"""
    provider = cp.from_dot_env_contents(
        """
A=
""",
        preserve_empty_strings=True,
    )
    assert_success(provider, [], Record(keys("A")))
    assert_success(provider, ["A"], Value(""))


def test_a_node_may_be_both_leaf_and_object():
    """a node may be both leaf and object"""
    provider = cp.from_dot_env_contents("""
OBJECT=value1
OBJECT_key1=value2
OBJECT_key2=value3
""")
    assert_success(provider, [], Record(keys("OBJECT")))
    assert_success(provider, ["OBJECT"], Record(keys("key1", "key2"), "value1"))
    assert_success(provider, ["OBJECT", "key1"], Value("value2"))
    assert_success(provider, ["OBJECT", "key2"], Value("value3"))


def test_a_node_may_be_both_leaf_and_array():
    """a node may be both leaf and array"""
    provider = cp.from_dot_env_contents("""
ARRAY=value1
ARRAY_0=value2
ARRAY_1=value3
""")
    assert_success(provider, [], Record(keys("ARRAY")))
    assert_success(provider, ["ARRAY"], Array(2, "value1"))
    assert_success(provider, ["ARRAY", 0], Value("value2"))
    assert_success(provider, ["ARRAY", 1], Value("value3"))


def test_arrays_are_supported():
    """arrays are supported"""
    provider = cp.from_dot_env_contents("""
ARRAY_0=value1
ARRAY_1=value2
""")
    assert_success(provider, [], Record(keys("ARRAY")))
    assert_success(provider, ["ARRAY"], Array(2))
    assert_success(provider, ["ARRAY", 0], Value("value1"))
    assert_success(provider, ["ARRAY", 1], Value("value2"))


def test_expansion_of_environment_variables_is_off_by_default():
    """expansion of environment variables is off by default"""
    provider = cp.from_dot_env_contents("""
PASSWORD="value"
DB_PASS=$PASSWORD
""")
    assert_success(provider, [], Record(keys("PASSWORD", "DB")))
    assert_success(provider, ["PASSWORD"], Value("value"))
    assert_success(provider, ["DB_PASS"], Value("$PASSWORD"))


def test_expansion_of_environment_variables_is_supported():
    """expansion of environment variables is supported"""
    provider = cp.from_dot_env_contents(
        """
PASSWORD="value"
DB_PASS=${PASSWORD}
""",
        expand_variables=True,
    )
    assert_success(provider, [], Record(keys("PASSWORD", "DB")))
    assert_success(provider, ["PASSWORD"], Value("value"))
    assert_success(provider, ["DB_PASS"], Value("value"))


def test_expands_referenced_values_as_literal_data():
    """expands referenced values as literal data"""
    provider = cp.from_dot_env_contents(
        """
SOURCE=a$&b$'c$`d
TARGET=${SOURCE}
ESCAPED=\\$SOURCE/$SOURCE
""",
        expand_variables=True,
    )
    assert_success(provider, ["TARGET"], Value("a$&b$'c$`d"))
    assert_success(provider, ["ESCAPED"], Value("$SOURCE/a$&b$'c$`d"))


def test_expands_adjacent_braced_references():
    """expands adjacent braced references"""
    provider = cp.from_dot_env_contents(
        """
A=first
B=second
VALUE=${A}${B}
""",
        expand_variables=True,
    )
    assert_success(provider, ["VALUE"], Value("firstsecond"))


def test_preserves_escaped_references_after_backslashes_and_inside_defaults():
    """preserves escaped references after backslashes and inside defaults"""
    provider = cp.from_dot_env_contents(
        """
SOURCE=value
BACKSLASH=before/\\\\$SOURCE/$SOURCE
DEFAULT=${UNSET:-\\$SOURCE}/$SOURCE
""",
        expand_variables=True,
    )
    assert_success(provider, ["BACKSLASH"], Value("before/\\$SOURCE/value"))
    assert_success(provider, ["DEFAULT"], Value("$SOURCE/value"))


def test_expansion_defaults_are_used_only_for_empty_or_unset_variables():
    """expansion defaults are used only for empty or unset variables"""
    provider = cp.from_dot_env_contents(
        """
SET=actual
EMPTY=
EXPANDS_EMPTY=$EMPTY
BRACED=a}b
FROM_SET=${SET:-fallback}
FROM_EMPTY=${EMPTY:-fallback}
FROM_UNSET=${UNSET:-fallback}
FROM_EXPANDS_EMPTY=${EXPANDS_EMPTY:-fallback}
NESTED=${UNSET:-${BRACED}}
""",
        expand_variables=True,
    )
    assert_success(provider, ["FROM_SET"], Value("actual"))
    assert_success(provider, ["FROM_EMPTY"], Value("fallback"))
    assert_success(provider, ["FROM_UNSET"], Value("fallback"))
    assert_success(provider, ["FROM_EXPANDS_EMPTY"], Value("fallback"))
    assert_success(provider, ["NESTED"], Value("a}b"))


def test_does_not_expand_missing_inherited_variables():
    """does not expand missing inherited variables"""
    provider = cp.from_dot_env_contents("VALUE=$constructor", expand_variables=True)
    assert_missing(provider, ["VALUE"])


def test_expands_self_and_circular_references_to_empty_values():
    """expands self and circular references to empty values"""
    provider = cp.from_dot_env_contents(
        """
PATH=$PATH:/opt/bin
A=$B
B=$A
SELF_DEFAULT=${SELF_DEFAULT:-fallback}
""",
        expand_variables=True,
    )
    assert_success(provider, ["PATH"], Value(":/opt/bin"))
    assert_missing(provider, ["A"])
    assert_success(provider, ["SELF_DEFAULT"], Value("fallback"))


def test_does_not_scan_expanded_text_again():
    """does not scan expanded text again"""
    provider = cp.from_dot_env_contents(
        """
USER=app
HOME_DIR=/home/$USER
LOG_DIR=${HOME_DIR}_logs
NAME=$USER${SUFFIX:-_v1}
LITERAL=$USER/$
""",
        expand_variables=True,
    )
    assert_success(provider, ["LOG_DIR"], Value("/home/app_logs"))
    assert_success(provider, ["NAME"], Value("app_v1"))
    assert_success(provider, ["LITERAL"], Value("app/$"))


def test_expands_long_sequences_of_adjacent_references_without_overflowing():
    """expands long sequences of adjacent references without overflowing"""
    provider = cp.from_dot_env_contents("A=a\nVALUE=" + "$A" * 20_000, expand_variables=True)
    assert_success(provider, ["VALUE"], Value("a" * 20_000))


# --- from_dot_env -----------------------------------------------------------------------


def _from_dot_env(
    eff: fx.Effect[cp.ConfigProvider, PlatformError, FileSystem], fs: NoopFileSystem
) -> cp.ConfigProvider:
    result = fx.run_sync(eff.result().pipe(fx.provide(file_system.layer_noop(fs))))
    assert isinstance(result, fx.Ok)
    return result.value


class _DotEnv(NoopFileSystem):
    """Reads every path as ``contents(path)``."""

    def __init__(self, contents: Callable[[str], str]) -> None:
        self.contents = contents

    def read_file_string(self, path: str, encoding: str = "utf-8") -> fx.Effect[str, PlatformError]:
        return fx.succeed(self.contents(path))


def test_should_load_configuration_from_env_file():
    """should load configuration from .env file"""
    provider = _from_dot_env(cp.from_dot_env(), _DotEnv(lambda path: f"PATH={path}\nA=1"))

    assert_success(provider, ["PATH"], Value(".env"))
    assert_success(provider, ["A"], Value("1"))


def test_should_support_path_option_to_specify_the_path_to_the_env_file():
    """should support `path` option to specify the path to the .env file"""
    provider = _from_dot_env(
        cp.from_dot_env("custom.env"), _DotEnv(lambda path: f"CUSTOM_PATH={path}\nA=1")
    )

    assert_success(provider, ["CUSTOM_PATH"], Value("custom.env"))
    assert_success(provider, ["A"], Value("1"))


def test_should_support_expand_variables_option():
    """should support `expandVariables` option"""
    provider = _from_dot_env(
        cp.from_dot_env(expand_variables=True),
        _DotEnv(lambda _: "PASSWORD=value\nDB_PASS=$PASSWORD"),
    )

    assert_success(provider, ["DB_PASS"], Value("value"))


def test_should_treat_empty_string_values_as_missing_while_preserving_structure_by_default():
    """should treat empty string values as missing while preserving structure by default"""
    provider = _from_dot_env(cp.from_dot_env(), _DotEnv(lambda _: "A="))

    assert_success(provider, [], Record(keys("A")))
    assert_missing(provider, ["A"])


def test_should_support_preserve_empty_strings_option():
    """should support `preserveEmptyStrings` option"""
    provider = _from_dot_env(cp.from_dot_env(preserve_empty_strings=True), _DotEnv(lambda _: "A="))

    assert_success(provider, ["A"], Value(""))


def test_fails_with_the_file_system_error_when_the_file_cannot_be_read():
    """fails with the FileSystem error when the file cannot be read"""
    error = system_error("PermissionDenied", module="FileSystem", method="read_file_string")

    class Denied(NoopFileSystem):
        def read_file_string(
            self, path: str, encoding: str = "utf-8"
        ) -> fx.Effect[str, PlatformError]:
            return fx.fail(error)

    result = fx.run_sync(
        cp.from_dot_env().result().pipe(fx.provide(file_system.layer_noop(Denied())))
    )

    assert result == fx.Err(error)


# --- from_dir ---------------------------------------------------------------------------


def _not_found(method: str) -> PlatformError:
    return system_error("NotFound", module="FileSystem", method=method)


class _Files(NoopFileSystem):
    """Files and directories held in dicts; anything else is ``NotFound``."""

    def __init__(self, files: dict[str, str], dirs: dict[str, list[str]] | None = None) -> None:
        self.files = files
        self.dirs = dirs or {}

    def read_file_string(self, path: str, encoding: str = "utf-8") -> fx.Effect[str, PlatformError]:
        if path in self.files:
            return fx.succeed(self.files[path])
        return fx.fail(_not_found("read_file_string"))

    def read_directory(
        self, path: str, *, recursive: bool = False
    ) -> fx.Effect[list[str], PlatformError]:
        if path in self.dirs:
            return fx.succeed(list(self.dirs[path]))
        return fx.fail(_not_found("read_directory"))


def _from_dir(fs: NoopFileSystem, root_path: str = "/", **options: bool) -> cp.ConfigProvider:
    return fx.run_sync(
        cp.from_dir(root_path, **options).pipe(
            fx.provide(layer.merge(file_system.layer_noop(fs), path_layer_posix))
        )
    )


def test_reads_trimmed_file_contents_at_root_and_nested_paths():
    """reads trimmed file contents at root and nested paths"""
    files = {
        "/secret": "keepitsafe\n",
        "/SHOUTING": "value",
        "/integer": "123",
        "/nested/config": "hello",
    }
    provider = _from_dir(_Files(files))

    assert_success(provider, ["secret"], Value("keepitsafe"))
    assert_success(provider, ["SHOUTING"], Value("value"))
    assert_success(provider, ["integer"], Value("123"))
    assert_success(provider, ["nested", "config"], Value("hello"))
    assert_missing(provider, ["missing"])


def test_treats_empty_files_as_missing_by_default():
    """treats empty files as missing by default"""
    provider = _from_dir(_Files({"/empty": ""}, {"/": ["empty"]}))

    assert_success(provider, [], Record(keys("empty")))
    assert_missing(provider, ["empty"])


def test_preserves_empty_files_when_requested():
    """preserves empty files when requested"""
    provider = _from_dir(_Files({"/empty": "\n"}), preserve_empty_strings=True)

    assert_success(provider, ["empty"], Value(""))


def test_reads_directory_entries_as_a_record():
    """reads directory entries as a record"""
    provider = _from_dir(_Files({}, {"/app": ["host", "port"]}))

    assert_success(provider, ["app"], Record(keys("host", "port")))


def test_wraps_non_not_found_failures_in_source_error():
    """wraps non-NotFound failures in SourceError"""
    cause = system_error("PermissionDenied", module="FileSystem", method="read_file_string")

    class Denied(NoopFileSystem):
        def read_file_string(
            self, path: str, encoding: str = "utf-8"
        ) -> fx.Effect[str, PlatformError]:
            return fx.fail(cause)

        def read_directory(
            self, path: str, *, recursive: bool = False
        ) -> fx.Effect[list[str], PlatformError]:
            return fx.fail(_not_found("read_directory"))

    provider = _from_dir(Denied(), "/config")

    assert_failure(
        provider, ["secret"], SourceError("Failed to read file at /config/secret", cause)
    )


# --- layers -----------------------------------------------------------------------------


@fx.fn
def _load_from_context(path: cp.PathInput):
    provider = yield from fx.CurrentConfigProvider()
    return (yield from provider.load(path))


def _run[A](eff: fx.Effect[A, SourceError]) -> A:
    result = fx.run_sync(eff.result())
    assert isinstance(result, fx.Ok)
    return result.value


def test_layer_installs_a_provider():
    """layer installs a provider"""
    result = _run(
        _load_from_context(["KEY"]).pipe(fx.provide(cp.layer(cp.from_unknown({"KEY": "value"}))))
    )

    assert result == Value("value")


def test_layer_accepts_an_effect_that_produces_a_provider():
    """layer accepts an Effect that produces a provider"""
    result = _run(
        _load_from_context(["KEY"]).pipe(
            fx.provide(cp.layer(fx.succeed(cp.from_unknown({"KEY": "value"}))))
        )
    )

    assert result == Value("value")


def test_layer_add_adds_an_effect_produced_provider_as_fallback():
    """layerAdd adds an Effect-produced provider as fallback"""
    current = cp.from_unknown({"CURRENT": "current", "SHARED": "current"})
    fallback = cp.from_unknown({"FALLBACK": "fallback", "SHARED": "fallback"})
    added = cp.layer_add(fx.succeed(fallback)).pipe(fx.provide(cp.layer(current)))

    result = _run(
        fx.all(
            _load_from_context(["CURRENT"]),
            _load_from_context(["FALLBACK"]),
            _load_from_context(["SHARED"]),
        ).pipe(fx.provide(added))
    )

    assert result == (Value("current"), Value("fallback"), Value("current"))


def test_layer_add_can_install_the_added_provider_as_primary():
    """layerAdd can install the added provider as primary"""
    current = cp.from_unknown({"CURRENT": "current", "SHARED": "current"})
    primary = cp.from_unknown({"PRIMARY": "primary", "SHARED": "primary"})
    added = cp.layer_add(primary, as_primary=True).pipe(fx.provide(cp.layer(current)))

    result = _run(
        fx.all(
            _load_from_context(["CURRENT"]),
            _load_from_context(["PRIMARY"]),
            _load_from_context(["SHARED"]),
        ).pipe(fx.provide(added))
    )

    assert result == (Value("current"), Value("primary"), Value("primary"))
