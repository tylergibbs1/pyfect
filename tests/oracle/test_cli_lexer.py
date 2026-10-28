"""Effect's ``test/cli/Lexer.test.ts``."""

from pyfect.cli._lexer import LongOption, ShortOption, Value, lex


def test_preserves_every_equals_sign_in_a_long_options_inline_value():
    """preserves every equals sign in a long option's inline value"""
    assert lex(["--query=left=right"]).tokens == (
        LongOption("query", "--query=left=right", "left=right"),
    )


def test_lexes_negative_numbers_as_values():
    """lexes negative numbers as values"""
    assert lex(["--lon", "-3.70", "-2", "-.5", "-1e3"]).tokens == (
        LongOption("lon", "--lon"),
        Value("-3.70"),
        Value("-2"),
        Value("-.5"),
        Value("-1e3"),
    )


def test_treats_equals_value_as_a_plain_value_instead_of_a_flag_with_an_empty_name():
    """treats --=value as a plain value instead of a flag with an empty name"""
    assert lex(["--=value"]).tokens == (Value("--=value"),)


def test_gives_an_inline_value_to_the_last_flag_of_a_short_option_cluster():
    """gives an inline value to the last flag of a short option cluster"""
    assert lex(["-vn=3", "-n=4"]).tokens == (
        ShortOption("v", "-v"),
        ShortOption("n", "-n", "3"),
        ShortOption("n", "-n", "4"),
    )


def test_still_lexes_short_options_that_are_not_negative_numbers():
    """still lexes short options that are not negative numbers"""
    assert lex(["-1a", "-e"]).tokens == (
        ShortOption("1", "-1"),
        ShortOption("a", "-a"),
        ShortOption("e", "-e"),
    )
