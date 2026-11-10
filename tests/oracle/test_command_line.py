"""Ports of Effect's ``process/CommandLine.test.ts``.

Each test's docstring is the Effect test title. A tagged template is its
text parts and values (``template(["git commit -m ", ""], message)``);
Effect's one-part helper is ``template([text])``.
"""

from __future__ import annotations

import pytest

from pyfect import redacted
from pyfect.process import command_line
from pyfect.process.command_line import CommandLineError, Word
from pyfect.result import Err, Ok, Result


def ok[A](result: Result[A, CommandLineError]) -> A:
    assert isinstance(result, Ok), result
    return result.value


def failure[A](result: Result[A, CommandLineError]) -> CommandLineError:
    assert isinstance(result, Err), f"expected a failure, got {result}"
    return result.error


def template(text: str) -> Result[list[Word], CommandLineError]:
    return command_line.template([text])


def test_quotes_for_posix_shells() -> None:
    """quotes for POSIX shells"""
    cases: list[tuple[Word, str]] = [
        ("plain", "plain"),
        ("path/to.file:1,2@x+y-z_", "path/to.file:1,2@x+y-z_"),
        ("", "''"),
        ("a b", "'a b'"),
        ("it's", "'it'\\''s'"),
        ("a\\b", "'a'\\\\'b'"),
        ("=ls", "'=ls'"),
        ("%self", "'%self'"),
        ("{a,b}", "'{a,b}'"),
        ("~", "'~'"),
        ("#x", "'#x'"),
        ("$HOME", "'$HOME'"),
        ("a\nb", "'a\nb'"),
        (redacted.make("a b"), "'a b'"),
    ]
    for word, expected in cases:
        assert ok(command_line.quote(word)) == expected, word
    assert failure(command_line.quote("a\0b")).reason == "NulCharacter"


def test_quotes_for_powershell() -> None:
    """quotes for PowerShell"""
    cases = [
        ("plain", "'plain'"),
        ("", "''"),
        ("it's", "'it''s'"),
        ("x\u2019; y\u2018", "'x\u2019\u2019; y\u2018\u2018'"),
        ("\u201a\u201b", "'\u201a\u201a\u201b\u201b'"),
        ("$env:HOME `n", "'$env:HOME `n'"),
    ]
    for word, expected in cases:
        assert ok(command_line.quote(word, format="powershell")) == expected, word


def test_quotes_windows_arguments() -> None:
    """quotes Windows arguments"""
    cases = [
        ("plain", "plain"),
        ("a\\b", "a\\b"),
        ("", '""'),
        ("a b", '"a b"'),
        ("a\tb", '"a\tb"'),
        ('a"b', '"a\\"b"'),
        ('a\\"b', '"a\\\\\\"b"'),
        ("a b\\", '"a b\\\\"'),
        ("a b\\\\", '"a b\\\\\\\\"'),
    ]
    for word, expected in cases:
        assert ok(command_line.quote(word, format="windows")) == expected, word


def test_joins_a_program_and_its_arguments() -> None:
    """joins a program and its arguments"""
    args = ["git", "commit", "-m", "fix: don't"]
    assert ok(command_line.join(args)) == "git commit -m 'fix: don'\\''t'"
    assert ok(command_line.join(args, format="powershell")) == "& 'git' 'commit' '-m' 'fix: don''t'"
    assert ok(command_line.join(args, format="windows")) == 'git commit -m "fix: don\'t"'
    assert ok(command_line.join([])) == ""
    for program in ("time", "nocorrect", "in"):
        assert ok(command_line.join([program, "x"])) == f"'{program}' x"
    error = failure(command_line.join(["echo", "a\0b"]))
    assert (error.reason, error.message) == ("NulCharacter", "Argument 1 contains a NUL character")


def test_quotes_windows_program_names_without_backslash_escapes() -> None:
    """quotes Windows program names without backslash escapes"""
    cases = [
        ("C:\\Program Files\\app.exe", '"C:\\Program Files\\app.exe"'),
        ("C:\\tools\\", "C:\\tools\\"),
        ("", '""'),
    ]
    for program, expected in cases:
        assert ok(command_line.join([program], format="windows")) == expected
    assert failure(command_line.join(['a"b'], format="windows")).reason == "InvalidArgument"


def test_rejects_the_argument_for_powershell() -> None:
    """rejects the argument --% for PowerShell"""
    error = failure(command_line.join(["node", "a", "--%"], format="powershell"))
    assert (error.reason, error.message) == (
        "InvalidArgument",
        'Argument 2 is "--%", which PowerShell drops when it calls a program',
    )
    assert ok(command_line.quote("--%", format="powershell")) == "'--%'"


def test_masks_redacted_words_escapes_control_characters_and_accepts_any_input() -> None:
    """masks Redacted words, escapes control characters and accepts any input"""
    words: list[Word] = ["curl", "-H", redacted.make("Authorization: hunter2"), "a\nb\x1b[2J\0"]
    assert command_line.display(words) == "curl -H <redacted> 'a\\nb\\u001b[2J\\u0000'"
    assert (
        command_line.display(words, format="powershell")
        == "& 'curl' '-H' <redacted> 'a\\nb\\u001b[2J\\u0000'"
    )
    assert command_line.display(['a"b', "c d"], format="windows") == '"a\\"b" "c d"'
    assert command_line.display([]) == ""
    assert command_line.display(["if", "x"]) == "'if' x"


def test_removes_posix_quotes_and_escapes() -> None:
    """removes POSIX quotes and escapes"""
    cases: list[tuple[str, list[str]]] = [
        ("", []),
        ("  a \t b  ", ["a", "b"]),
        ("a 'b c' d", ["a", "b c", "d"]),
        ('a "b \\"c\\" \\$d \\\\ \\x"', ["a", 'b "c" $d \\ \\x']),
        ("a\\ b", ["a b"]),
        ("'' \"\"", ["", ""]),
        ("a''b", ["ab"]),
        ("a\\\nb", ["ab"]),
        ("'a\nb' \"c\nd\"", ["a\nb", "c\nd"]),
        ("'$HOME' \\$HOME \"cost$\" cost$", ["$HOME", "$HOME", "cost$", "cost$"]),
        ("find . -exec rm {} \\;", ["find", ".", "-exec", "rm", "{}", ";"]),
        ("env FOO=bar --x=1 a#b x~ '!'", ["env", "FOO=bar", "--x=1", "a#b", "x~", "!"]),
        ("'FOO=bar' cmd", ["FOO=bar", "cmd"]),
        ("a\0b c", ["a\0b", "c"]),
    ]
    for line, expected in cases:
        assert ok(template(line)) == expected, line


def test_rejects_syntax_that_needs_a_shell() -> None:
    """rejects syntax that needs a shell"""
    cases = [
        ("a | b", "UnsupportedSyntax"),
        ("a && b", "UnsupportedSyntax"),
        ("a; b", "UnsupportedSyntax"),
        ("a >f", "UnsupportedSyntax"),
        ("(a)", "UnsupportedSyntax"),
        ("echo $HOME", "UnsupportedSyntax"),
        ("echo ${x}", "UnsupportedSyntax"),
        ("echo $(id)", "UnsupportedSyntax"),
        ("echo `id`", "UnsupportedSyntax"),
        ('echo "a $x"', "UnsupportedSyntax"),
        ("echo $'a'", "UnsupportedSyntax"),
        ("ls *.txt", "UnsupportedSyntax"),
        ("curl x?a=1", "UnsupportedSyntax"),
        ("ls [ab]", "UnsupportedSyntax"),
        ("cd ~", "UnsupportedSyntax"),
        ("echo #x", "UnsupportedSyntax"),
        ("echo {a,b}", "UnsupportedSyntax"),
        ("echo a{1..3}", "UnsupportedSyntax"),
        ("=ls", "UnsupportedSyntax"),
        ("FOO=bar cmd", "UnsupportedSyntax"),
        ("FOO+=bar cmd", "UnsupportedSyntax"),
        ("'open", "UnterminatedQuote"),
        ('a "b', "UnterminatedQuote"),
        ("a\\", "InvalidEscape"),
    ]
    for line, reason in cases:
        assert failure(template(line)).reason == reason, line


def test_splits_the_text_and_keeps_values_literal() -> None:
    """splits the text and keeps values literal"""
    message = "fix: a b; $HOME"
    assert ok(command_line.template(["git commit -m ", " \"two words\" 'it''s'"], message)) == [
        "git",
        "commit",
        "-m",
        message,
        "two words",
        "its",
    ]
    assert ok(command_line.template(["docker run\n          --rm ", ""], "img")) == [
        "docker",
        "run",
        "--rm",
        "img",
    ]
    assert ok(command_line.template(["if true"])) == ["if", "true"]


def test_joins_values_with_the_surrounding_argument() -> None:
    """joins values with the surrounding argument"""
    cases: list[tuple[Result[list[Word], CommandLineError], list[str]]] = [
        (command_line.template(["--x=", " ", ""], 1, True), ["--x=1", "true"]),
        (command_line.template(['"', " ", '"'], "a", "b"), ["a b"]),
        (command_line.template(["'", "'-y"], "$x"), ["$x-y"]),
        (command_line.template(["cost $", ""], 5), ["cost", "$5"]),
        (command_line.template(["a ", ""], ""), ["a", ""]),
        (command_line.template(["a ", ""], "b\0"), ["a", "b\0"]),
    ]
    for result, expected in cases:
        assert ok(result) == expected


def test_adds_one_argument_per_array_element() -> None:
    """adds one argument per array element"""
    assert ok(command_line.template(["ls ", " x"], ["-l", "a b"])) == ["ls", "-l", "a b", "x"]
    assert ok(command_line.template(["ls ", " x"], [])) == ["ls", "x"]
    assert ok(command_line.template(["ls ", ""], ["a"])) == ["ls", "a"]
    for result in (
        command_line.template(["--x=", ""], ["a"]),
        command_line.template(["", "b"], ["a"]),
    ):
        assert failure(result).reason == "UnsupportedSyntax"


def test_makes_arguments_with_redacted_values_redacted() -> None:
    """makes arguments with Redacted values Redacted"""
    password = redacted.make("hunter2")
    words = ok(command_line.template(['psql "--password=', '" ', " -h db"], password, [password]))
    assert len(words) == 5
    second = words[1]
    assert isinstance(second, redacted.Redacted)
    assert redacted.value(second) == "--password=hunter2"
    assert words[2] is password
    assert command_line.display(words) == "psql <redacted> <redacted> -h db"
    assert ok(command_line.join(words)) == "psql '--password=hunter2' hunter2 -h db"


def test_rejects_an_unclosed_quote_around_a_value_and_invalid_escapes() -> None:
    """rejects an unclosed quote around a value and invalid escapes

    Adapted: an invalid escape such as ``\\u`` without hex digits is a
    ``SyntaxError`` where Python compiles the literal, so it never reaches
    ``template`` (JavaScript gives the tag an undefined text part instead)."""
    assert failure(command_line.template(['echo "', ""], "a")).reason == "UnterminatedQuote"
    with pytest.raises(SyntaxError):
        compile('"echo \\unicode"', "<template>", "eval")


@pytest.mark.skipif(not hasattr(__import__("string"), "templatelib"), reason="t-strings: 3.14")
def test_t_strings_are_templates() -> None:
    """A t-string is a template: its values are the interpolations."""
    message = "a | b"
    words = eval('t"git commit -m {message} \\"two words\\""')
    assert ok(command_line.template(words)) == ["git", "commit", "-m", message, "two words"]
    with pytest.raises(TypeError):
        command_line.template(words, "extra")
