"""Effect's ``test/cli/completions/completions.test.ts``. The PowerShell
replay test runs only where ``pwsh`` is installed, as in Effect."""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT, run_program

import pyfect as fx
from pyfect.cli import Argument, Config, Flag, command
from pyfect.cli import completions as Completions
from pyfect.cli.completions import bash as Bash
from pyfect.cli.completions import fish as Fish
from pyfect.cli.completions import powershell as PowerShell
from pyfect.cli.completions import zsh as Zsh
from pyfect.cli.completions._descriptor import (
    ArgumentDescriptor,
    Choice,
    CommandDescriptor,
    FlagDescriptor,
    from_command,
)

from ._comprehensive_cli import comprehensive_cli

# --- shared fixtures -----------------------------------------------------------------


class _Simple(Config):
    name = Argument.string("name").with_description("Name to greet")
    loud = Flag.boolean("loud").with_alias("l").with_description("Shout the greeting")
    times = Flag.integer("times").with_description("Repeat count").with_default(1)


simple_cmd = command.make("greet", _Simple).with_description("Greet someone")


class _Start(Config):
    port = Flag.integer("port").with_alias("p").with_description("Port number")
    daemon = Flag.boolean("daemon").with_description("Run as daemon")


class _Stop(Config):
    force = Flag.boolean("force").with_alias("f").with_description("Force stop")


class _Server(Config):
    verbose = Flag.boolean("verbose").with_alias("v")
    config = Flag.string("config")


with_subcommands = (
    command.make("server", _Server)
    .with_description("Server management")
    .with_subcommands(
        command.make("start", _Start).with_description("Start the server"),
        command.make("stop", _Stop).with_description("Stop the server"),
    )
)


class _Choices(Config):
    env = Flag.literals("env", ["dev", "staging", "prod"]).with_description("Target environment")
    region = Argument.literals("region", ["us-east", "eu-west", "ap-south"]).with_description(
        "Deployment region"
    )


with_choices = command.make("deploy", _Choices).with_description("Deploy application")

tricky_values = [
    "it's-fine",
    "node:20",
    "with space",
    "(whoami)",
    "#tag",
    "$HOME",
    "back\\slash",
    'say"hi"',
    "a*b",
    "a;b",
    "~x",
    "foo'",
    "a!b",
    "\U0001f680",
]


class _Tricky(Config):
    mode = Flag.literals("mode", tricky_values).with_description("Deploy mode")
    target = Argument.literals(
        "target", ["o'clock", "a:b", "{x,y}", "a\U0001f600b"]
    ).with_description("Deployment target")


with_tricky_choices = command.make("deploy", _Tricky).with_description("Deploy application")


class _Paths(Config):
    input = Flag.file("input").with_description("Input file")
    out_dir = Flag.directory("output-dir").with_description("Output directory")
    source = Argument.file("source", must_exist=False).with_description("Source file")


with_paths = command.make("process", _Paths).with_description("Process files")


class _Example(Config):
    directory = Argument.directory("directory").with_description("Directory to start in").optional()


with_optional_directory_and_subcommands = command.make("example", _Example).with_subcommands(
    command.make("serve").with_description("Start the server")
)


class _Action(Config):
    dry_run = Flag.boolean("dry-run").with_description("Dry run mode")


nested_3_levels = command.make("top").with_subcommands(
    command.make("sub").with_subcommands(
        command.make("action", _Action).with_description("Perform action")
    )
)

empty_cmd = command.make("noop").with_description("Does nothing")


def leaf(name: str, flag: str) -> CommandDescriptor:
    return CommandDescriptor(name, None, (FlagDescriptor(flag, (), None, "Boolean"),))


def choices_helper_source(script: str) -> str:
    start = script.index("_deploy--choices()")
    end = script.index("\n}\n", start)
    return script[start : end + 2]


def lines_with(script: str, needle: str) -> str:
    return "\n".join(line.strip() for line in script.split("\n") if needle in line)


BASH_TRICKY_CHOICES = "\n".join(
    [
        "_deploy--choices \"$cur\" \"$_comp_word\" 'it'\\''s-fine' 'node:20' 'with space' '(whoami)' '#tag' '$HOME' 'back\\slash' 'say\"hi\"' 'a*b' 'a;b' '~x' 'foo'\\''' 'a!b' '🚀'",  # noqa: E501
        "_deploy--choices \"$cur\" \"$_comp_word\" 'o'\\''clock' 'a:b' '{x,y}' 'a😀b'",
    ]
)
BASH_CHOICES_HELPER = "\n".join(
    [
        "_deploy--choices()",
        "{",
        '  local _cur="$1" _word="$2"; shift 2',
        "",
        '  local _head="${_cur%"$_word"}"',
        '  local _open=""',
        '  case "$_head" in',
        "    *\\') _open=\"'\" ;;",
        "    *\\\") _open='\"' ;;",
        "  esac",
        "",
        '  local _prefix="$_cur" _committed="$_head"',
        "  _prefix=${_prefix//\\\\/}; _prefix=${_prefix//\\\"/}; _prefix=${_prefix//\\'/}",
        "  _committed=${_committed//\\\\/}; _committed=${_committed//\\\"/}; _committed=${_committed//\\'/}",  # noqa: E501
        "",
        "  COMPREPLY=()",
        "  local _choice _rest _match",
        '  for _choice in "$@"; do',
        '    [[ "$_choice" == "$_prefix"* ]] || continue',
        '    _rest="${_choice#"$_committed"}"',
        '    case "$_open" in',
        '      "\'")',
        '        if [[ "$_head" == "\'" ]]; then',
        "          _match=${_rest//\\'/\\'\\\\\\'\\'}",
        "        else",
        '          [[ "$_rest" == *\\\'* ]] && continue',
        '          _match="$_rest"',
        "        fi",
        "        ;;",
        "      '\"')",
        '        _match="${_rest//\\\\/\\\\\\\\}"',
        '        _match="${_match//\\$/\\\\$}"',
        '        _match="${_match//\\`/\\\\\\`}"',
        '        _match="${_match//\\"/\\\\\\"}"',
        "        ;;",
        "      *)",
        "        printf -v _match '%q' \"$_rest\"",
        '        [[ -z "$_head" && "$_match" == \'~\'* ]] && _match="\\\\$_match"',
        "        ;;",
        "    esac",
        '    [[ -n "$_open" && "$_match" == *"$_open" ]] && _match+="$_open"',
        '    COMPREPLY+=("$_match")',
        "  done",
        "}",
    ]
)
ZSH_TRICKY_MODE = "'(--mode)--mode[Deploy mode]:value:(it\\'\\''s-fine node\\:20 with\\ space \\(whoami\\) \\#tag \\$HOME back\\\\slash say\\\"hi\\\" a\\*b a\\;b \\~x foo\\'\\'' a\\!b \\🚀)'"  # noqa: E501
ZSH_TRICKY_TARGET = "':Deployment target:(o\\'\\''clock a\\:b \\{x,y\\} a\\😀b)'"
FISH_TRICKY = "\n".join(
    [
        "complete -c deploy -n 'begin; not __fish_contains_opt mode; or contains -- (commandline -poc)[-1] --mode; end' -l mode -d 'Deploy mode' -r -f -a 'it\\\\\\'s-fine node\\\\:20 with\\\\ space \\\\(whoami\\\\) \\\\#tag \\\\$HOME back\\\\\\\\slash say\\\\\"hi\\\\\" a\\\\*b a\\\\;b \\\\~x foo\\\\\\' a\\\\!b \\\\🚀'",  # noqa: E501
        "complete -c deploy -r -f -a 'o\\\\\\'clock a\\\\:b \\\\{x,y\\\\} a\\\\😀b' -d 'Deployment target'",  # noqa: E501
    ]
)


# --- Bash completions ----------------------------------------------------------------


def test_completes_the_active_positional_argument_instead_of_always_using_the_first():
    """completes the active positional argument instead of always using the first"""
    descriptor = CommandDescriptor(
        "tool",
        None,
        (
            FlagDescriptor("verbose", ("v",), None, "Boolean"),
            FlagDescriptor("format", ("f",), None, Choice(("json", "text"))),
        ),
        (
            ArgumentDescriptor("source", None, True, False, Choice(("one",))),
            ArgumentDescriptor("target", None, True, False, Choice(("two",))),
        ),
    )
    script = Bash.generate("tool", descriptor)
    assert "for ((i = _command_index + 1; i < cword; i++)); do" in script
    assert "--verbose|-v|--no-verbose) ;;" in script
    assert "--format|-f) _skip_next=1 ;;" in script
    assert "--format=*|-f=*) ;;" in script
    assert '0)\n      _tool--choices "$cur" "$_comp_word" \'one\'' in script
    assert '1)\n      _tool--choices "$cur" "$_comp_word" \'two\'' in script


def test_generates_completion_function_for_root_command():
    """generates completion function for root command"""
    script = Bash.generate("greet", from_command(simple_cmd))
    assert "_greet()" in script
    assert "complete -F _greet greet" in script
    assert '_init_completion -n "$COMP_WORDBREAKS" || return' in script


def test_bash_includes_subcommand_names_in_word_list():
    """includes subcommand names in word list"""
    script = Bash.generate("server", from_command(with_subcommands))
    assert "start)" in script
    assert "stop)" in script


def test_does_not_dispatch_subcommands_from_flag_values():
    """does not dispatch subcommands from flag values"""
    script = Bash.generate("server", from_command(with_subcommands))
    assert (
        "for ((i = _command_index + 1; i < cword; i++)); do\n"
        "    if (( _skip_next )); then\n"
        "      _skip_next=0\n"
        "      continue\n"
        "    fi\n"
        '    case "${words[i]}" in\n'
        "      --config) _skip_next=1 ;;\n"
        "      --config=*) ;;\n"
        "      start)"
    ) in script


def test_includes_long_flag_names_with_double_dash_prefix():
    """includes long flag names with -- prefix"""
    script = Bash.generate("greet", from_command(simple_cmd))
    assert "--loud" in script
    assert "--times" in script


def test_includes_short_flag_aliases():
    """includes short flag aliases"""
    assert "-l" in Bash.generate("greet", from_command(simple_cmd))


def test_bash_generates_no_flag_for_boolean_flags():
    """generates --no-<flag> for boolean flags"""
    assert "--no-loud" in Bash.generate("greet", from_command(simple_cmd))


def _script_args(command: str) -> list[str]:
    """``script`` arguments that run ``command`` on a pseudo-terminal."""
    if sys.platform == "linux":
        return ["script", "-qec", command, "/dev/null"]
    return ["script", "-q", "/dev/null", *command.split(" ")]


def _has_readline() -> bool:
    if shutil.which("bash") is None or shutil.which("script") is None:
        return False
    try:
        run_program(["bash", "--noprofile", "--norc", "-c", "compgen -W x"], cwd=".")
        run_program(_script_args("bash --noprofile --norc -c true"), cwd=".")
    except subprocess.CalledProcessError:
        return False
    return True


_HAS_READLINE = _has_readline()


_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
"""Terminal control sequences, such as bracketed paste mode, around the output."""


def _type_into(args: list[str], directory: str, keys: str) -> str:
    """Runs ``args`` and types ``keys`` once its prompt shows: typed earlier,
    the pseudo-terminal can take them before Bash's readline reads them."""
    process = subprocess.Popen(
        args,
        cwd=directory,
        env={**os.environ, "HOME": directory},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    seen = b""
    deadline = time.monotonic() + SUBPROCESS_TIMEOUT
    while b"$ " not in seen and time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.1)
        if ready:
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            seen += chunk
    try:
        rest, _ = process.communicate(keys.encode(), timeout=SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        rest, _ = process.communicate()
    return (seen + rest).decode(errors="replace")


def _replay_bash_completion(line: str) -> list[str]:
    """Type ``line``, a tab and Enter into interactive Bash in a directory of
    ``process`` fixtures, and return the arguments ``process`` receives."""
    with tempfile.TemporaryDirectory(prefix="pyfect-cli-bash-") as directory:
        root = Path(directory)
        (root / "project files").mkdir()
        for name in ("project.txt", "report data.txt", "report.txt"):
            (root / name).write_text("")
        (root / "rc.bash").write_text(
            "\n".join(
                [
                    Bash.generate("process", from_command(with_paths)),
                    "process() { printf '<%s>\\n' \"$@\"; }",
                    "PS1='$ ' TMOUT=1",
                ]
            )
        )
        # Ctrl-D exits, or ends a quote left open; TMOUT exits once input runs out.
        output = _type_into(
            _script_args("bash --noprofile --rcfile rc.bash -i"),
            directory,
            f"{line}\t\n\x04exit\n",
        )
        return [
            text[1:-1].replace(directory, "~", 1)
            for text in _ESCAPES.sub("", output).replace("\r", "").split("\n")
            if text.startswith("<") and text.endswith(">")
        ]


@pytest.mark.skipif(not _HAS_READLINE, reason="no interactive Bash with readline")
def test_completes_paths_containing_spaces_as_one_argument():
    """completes paths containing spaces as one argument"""
    assert _replay_bash_completion("process --input report\\ d") == [
        "--input",
        "report data.txt",
    ]
    assert _replay_bash_completion("process --output-dir pro") == [
        "--output-dir",
        "project files",
    ]


@pytest.mark.skipif(not _HAS_READLINE, reason="no interactive Bash with readline")
def test_keeps_an_expandable_or_quoted_directory_as_typed():
    """keeps an expandable or quoted directory as typed"""
    assert _replay_bash_completion("process --input $HOME/report\\ d") == [
        "--input",
        "~/report data.txt",
    ]
    assert _replay_bash_completion('process --input "./"rep') == ["--input", "./report"]


def test_inlines_choice_values_for_choice_flags():
    """inlines choice values for choice flags"""
    script = Bash.generate("deploy", from_command(with_choices))
    assert "_deploy--choices \"$cur\" \"$_comp_word\" 'dev' 'staging' 'prod'" in script


def test_quotes_choice_values_instead_of_exposing_them_to_compgen_w_re_expansion():
    """quotes choice values instead of exposing them to compgen -W re-expansion"""
    script = Bash.generate("deploy", from_command(with_tricky_choices))
    assert lines_with(script, '_deploy--choices "$cur"') == BASH_TRICKY_CHOICES
    assert "compgen -W 'it" not in script


def test_splits_words_on_whitespace_only_so_a_value_holding_a_word_break_character_stays_one_word():
    """splits words on whitespace only, so a value holding a word-break character stays one word"""
    script = Bash.generate("deploy", from_command(with_tricky_choices))
    assert '_init_completion -n "$COMP_WORDBREAKS" || return' in script


def test_emits_the_choice_helper():
    """emits the choice helper"""
    script = Bash.generate("deploy", from_command(with_tricky_choices))
    assert choices_helper_source(script) == BASH_CHOICES_HELPER


def test_bash_generates_separate_functions_for_nested_subcommands():
    """generates separate functions for nested subcommands"""
    script = Bash.generate("server", from_command(with_subcommands))
    assert "_server()" in script
    assert "_server_start()" in script
    assert "_server_stop()" in script
    assert '_server_start "$i"' in script


def test_handles_commands_with_no_subcommands():
    """handles commands with no subcommands"""
    script = Bash.generate("noop", from_command(empty_cmd))
    assert "_noop()" in script
    assert "complete -F _noop noop" in script


def test_generates_deeply_nested_functions():
    """generates deeply nested functions"""
    script = Bash.generate("top", from_command(nested_3_levels))
    assert "_top()" in script
    assert "_top_sub()" in script
    assert "_top_sub_action()" in script


def test_bash_wraps_script_in_begin_end_markers():
    """wraps script in begin/end markers"""
    script = Bash.generate("greet", from_command(simple_cmd))
    assert "###-begin-greet-completions-###" in script
    assert "###-end-greet-completions-###" in script


def test_groups_flag_aliases_for_used_flag_filtering():
    """groups flag aliases for used-flag filtering"""
    script = Bash.generate("greet", from_command(simple_cmd))
    assert "--loud|-l|--no-loud) _used_0=1 ;;" in script
    assert "--times) _used_1=1 ;;" in script
    assert '[[ -n "$_used_0" ]] || _filtered_flags+=" --loud -l --no-loud"' in script
    assert '[[ -n "$_used_1" ]] || _filtered_flags+=" --times"' in script
    assert 'compgen -W "$_filtered_flags"' in script


def test_does_not_generate_flag_groups_for_commands_with_no_flags():
    """does not generate flag groups for commands with no flags"""
    script = Bash.generate("noop", from_command(empty_cmd))
    assert "_used_0" not in script
    assert "_filtered_flags" not in script


def test_uses_no_bash_4_syntax_so_the_script_runs_on_the_bash_mac_os_ships():
    """uses no bash 4 syntax, so the script runs on the bash macOS ships"""
    script = Bash.generate("comprehensive", from_command(comprehensive_cli))
    assert "local -A" not in script
    assert "declare -A" not in script


def test_includes_inline_init_completion_fallback():
    """includes inline _init_completion fallback"""
    script = Bash.generate("greet", from_command(simple_cmd))
    assert "if ! type _init_completion &>/dev/null; then" in script
    assert "COMPREPLY=()" in script
    assert 'if [[ "$_line" == [[:blank:]]* ]]; then' in script
    assert "((_i == COMP_CWORD)) && cword=$_j" in script
    assert 'cur="${words[cword]}"' in script


# --- Zsh completions -----------------------------------------------------------------


def test_generates_arguments_specs_for_flags():
    """generates _arguments specs for flags"""
    script = Zsh.generate("greet", from_command(simple_cmd))
    assert "_arguments" in script
    assert "--loud" in script
    assert "--times" in script


def test_includes_flag_descriptions_in_specs():
    """includes flag descriptions in specs"""
    script = Zsh.generate("greet", from_command(simple_cmd))
    assert "Shout the greeting" in script
    assert "Repeat count" in script


def test_includes_subcommand_descriptions_with_describe():
    """includes subcommand descriptions with _describe"""
    script = Zsh.generate("server", from_command(with_subcommands))
    assert "_describe" in script
    assert "Start the server" in script
    assert "Stop the server" in script


def test_zsh_generates_no_flag_for_boolean_flags():
    """generates --no-<flag> for boolean flags"""
    assert "--no-loud" in Zsh.generate("greet", from_command(simple_cmd))


def test_uses_files_for_file_type_flags():
    """uses _files for file-type flags"""
    assert "_files" in Zsh.generate("process", from_command(with_paths))


def test_uses_directories_for_directory_type_flags():
    """uses _directories for directory-type flags"""
    assert "_directories" in Zsh.generate("process", from_command(with_paths))


def test_inlines_choice_values_with_val1_val2_syntax():
    """inlines choice values with (val1 val2) syntax"""
    assert "(dev staging prod)" in Zsh.generate("deploy", from_command(with_choices))


def test_generates_handler_functions_for_nested_subcommands():
    """generates handler functions for nested subcommands"""
    script = Zsh.generate("server", from_command(with_subcommands))
    assert "_server()" in script
    assert "_server_start()" in script
    assert "_server_stop()" in script


def test_generates_argument_specs_for_positional_arguments():
    """generates argument specs for positional arguments"""
    assert "Name to greet" in Zsh.generate("greet", from_command(simple_cmd))


def test_generates_choice_argument_completions():
    """generates choice argument completions"""
    assert "(us-east eu-west ap-south)" in Zsh.generate("deploy", from_command(with_choices))


def test_escapes_choice_values_for_both_the_spec_quoting_and_the_action_list_re_parse():
    """escapes choice values for both the spec quoting and the action list re-parse"""
    script = Zsh.generate("deploy", from_command(with_tricky_choices))
    assert lines_with(script, ":value:(") == ZSH_TRICKY_MODE
    assert lines_with(script, "Deployment target") == ZSH_TRICKY_TARGET


def test_escapes_a_closing_bracket_in_flag_descriptions():
    """escapes a closing bracket in flag descriptions"""

    class Deploy(Config):
        level = Flag.literals("level", ["debug", "info"]).with_description("Log level [info]")

    script = Zsh.generate("deploy", from_command(command.make("deploy", Deploy)))
    assert "'(--level)--level[Log level [info\\]]:value:(debug info)'" in script


def test_uses_alternative_argument_sets_for_positional_arguments_and_subcommands():
    """uses alternative argument sets for positional arguments and subcommands"""
    script = Zsh.generate("example", from_command(with_optional_directory_and_subcommands))
    assert (
        "    -\n"
        "    parent-arguments\n"
        "    ':Directory to start in:_directories'\n"
        "    -\n"
        "    subcommands\n"
        "    '1:command:->command'\n"
        "    '*::arg:->args'"
    ) in script
    assert ("    ':Directory to start in:_directories'\n    '1:command:->command'") not in script


def test_starts_with_compdef_directive():
    """starts with #compdef directive"""
    assert Zsh.generate("greet", from_command(simple_cmd)).startswith("#compdef greet")


def test_zsh_wraps_script_in_begin_end_markers():
    """wraps script in begin/end markers"""
    script = Zsh.generate("greet", from_command(simple_cmd))
    assert "###-begin-greet-completions-###" in script
    assert "###-end-greet-completions-###" in script


def test_declares_state_machine_locals_for_commands_with_subcommands():
    """declares state machine locals for commands with subcommands"""
    script = Zsh.generate("server", from_command(with_subcommands))
    assert "local context state state_descr line" in script
    assert "typeset -A opt_args" in script


def test_does_not_declare_state_machine_locals_for_leaf_commands():
    """does not declare state machine locals for leaf commands"""
    script = Zsh.generate("greet", from_command(simple_cmd))
    assert "local context state state_descr line" not in script
    assert "typeset -A opt_args" not in script


def test_uses_specs_array_instead_of_line_continuations():
    """uses specs array instead of line continuations"""
    script = Zsh.generate("greet", from_command(simple_cmd))
    assert "local -a specs" in script
    assert "specs=(" in script
    assert '_arguments "${specs[@]}"' in script


def test_generates_exclusion_groups_for_flag_aliases():
    """generates exclusion groups for flag aliases"""
    script = Zsh.generate("greet", from_command(simple_cmd))
    assert "'(--loud -l --no-loud)--loud[Shout the greeting]'" in script
    assert "'(--loud -l --no-loud)-l[Shout the greeting]'" in script
    assert "'(--loud -l --no-loud)--no-loud[Disable loud]'" in script


def test_generates_exclusion_group_for_flags_without_aliases():
    """generates exclusion group for flags without aliases"""
    script = Zsh.generate("greet", from_command(simple_cmd))
    assert "'(--times)--times[Repeat count]:integer:'" in script


def test_zsh_uses_disable_description_for_boolean_negation():
    """uses Disable description for boolean negation"""
    assert "--no-loud[Disable loud]" in Zsh.generate("greet", from_command(simple_cmd))


# --- Fish completions ----------------------------------------------------------------


def test_scopes_nested_completions_by_the_full_command_path():
    """scopes nested completions by the full command path"""
    descriptor = CommandDescriptor(
        "tool",
        None,
        subcommands=(
            CommandDescriptor("alpha", None, subcommands=(leaf("common", "alpha-only"),)),
            CommandDescriptor("beta", None, subcommands=(leaf("common", "beta-only"),)),
        ),
    )
    lines = Fish.generate("tool", descriptor).split("\n")
    alpha_only = next(line for line in lines if "-l alpha-only" in line)
    beta_only = next(line for line in lines if "-l beta-only" in line)
    assert "__fish_seen_subcommand_from alpha; and __fish_seen_subcommand_from common" in alpha_only
    assert "__fish_seen_subcommand_from beta; and __fish_seen_subcommand_from common" in beta_only


def test_generates_complete_commands_for_root_subcommands():
    """generates complete commands for root subcommands"""
    script = Fish.generate("server", from_command(with_subcommands))
    assert "complete -c server" in script
    assert "-a 'start'" in script
    assert "-a 'stop'" in script


def test_generates_complete_commands_for_flags_with_l_and_s():
    """generates complete commands for flags with -l and -s"""
    script = Fish.generate("greet", from_command(simple_cmd))
    assert "-l loud" in script
    assert "-s l" in script
    assert "-l times" in script


def test_fish_generates_no_flag_for_boolean_flags():
    """generates --no-<flag> for boolean flags"""
    assert "-l no-loud" in Fish.generate("greet", from_command(simple_cmd))


def test_uses_r_f_for_file_type_flags():
    """uses -r -F for file-type flags"""
    assert "-r -F" in Fish.generate("process", from_command(with_paths))


def test_uses_r_f_a_for_choice_flags():
    """uses -r -f -a for choice flags"""
    assert "-r -f -a 'dev staging prod'" in Fish.generate("deploy", from_command(with_choices))


def test_escapes_choice_values_for_both_the_string_quoting_and_the_expansion_of_the_a_list():
    """escapes choice values for both the string quoting and the expansion of the -a list"""
    script = Fish.generate("deploy", from_command(with_tricky_choices))
    assert lines_with(script, "-r -f -a") == FISH_TRICKY


def test_escapes_backslashes_in_descriptions_before_quotes():
    """escapes backslashes in descriptions before quotes"""

    class Deploy(Config):
        mode = Flag.literals("mode", ["a"]).with_description("Path like C:\\")

    script = Fish.generate("deploy", from_command(command.make("deploy", Deploy)))
    assert "-d 'Path like C:\\\\'" in script


def test_uses_n_conditions_for_nested_subcommand_flags():
    """uses -n conditions for nested subcommand flags"""
    script = Fish.generate("server", from_command(with_subcommands))
    assert "__fish_seen_subcommand_from start" in script
    assert "__fish_seen_subcommand_from stop" in script


def test_includes_descriptions_with_d_flag():
    """includes descriptions with -d flag"""
    script = Fish.generate("server", from_command(with_subcommands))
    assert "-d 'Start the server'" in script
    assert "-d 'Stop the server'" in script


def test_handles_deeply_nested_command_paths():
    """handles deeply nested command paths"""
    script = Fish.generate("top", from_command(nested_3_levels))
    assert "__fish_seen_subcommand_from action" in script
    assert "-l dry-run" in script


def test_handles_commands_with_no_flags():
    """handles commands with no flags"""
    script = Fish.generate("noop", from_command(empty_cmd))
    assert "###-begin-noop-completions-###" in script
    assert "###-end-noop-completions-###" in script


def test_uses_fish_use_subcommand_for_root_level():
    """uses __fish_use_subcommand for root level"""
    assert "__fish_use_subcommand" in Fish.generate("server", from_command(with_subcommands))


def test_fish_wraps_script_in_begin_end_markers():
    """wraps script in begin/end markers"""
    script = Fish.generate("greet", from_command(simple_cmd))
    assert "###-begin-greet-completions-###" in script
    assert "###-end-greet-completions-###" in script


def test_generates_used_flag_dedup_conditions():
    """generates used-flag dedup conditions"""
    script = Fish.generate("greet", from_command(simple_cmd))
    assert "not __fish_contains_opt -s l loud no-loud" in script
    lines = script.split("\n")
    times_long = next(line for line in lines if "-l times" in line)
    assert (
        "-n 'begin; not __fish_contains_opt times; or contains -- (commandline -poc)[-1] "
        "--times; end'"
    ) in times_long
    times_arg = next(line for line in lines if "-a '--times'" in line)
    assert "not __fish_contains_opt times" in times_arg


def test_combines_subcommand_and_dedup_conditions():
    """combines subcommand and dedup conditions"""
    script = Fish.generate("server", from_command(with_subcommands))
    assert (
        "__fish_seen_subcommand_from start; and not __fish_contains_opt daemon no-daemon" in script
    )
    lines = script.split("\n")
    port_long = next(line for line in lines if "-l port" in line)
    assert (
        "-n '__fish_seen_subcommand_from start; and begin; not __fish_contains_opt -s p port; "
        "or contains -- (commandline -poc)[-1] --port -p; end'"
    ) in port_long
    port_arg = next(line for line in lines if "-a '--port'" in line)
    assert "not __fish_contains_opt -s p port" in port_arg


def test_root_level_subcommands_use_fish_use_subcommand_without_child_guard():
    """root-level subcommands use __fish_use_subcommand without child guard"""
    script = Fish.generate("server", from_command(with_subcommands))
    assert "-n '__fish_use_subcommand' -f -a 'start'" in script
    assert "-n '__fish_use_subcommand' -f -a 'stop'" in script


def test_guards_nested_child_subcommands_against_re_offering():
    """guards nested child subcommands against re-offering"""
    script = Fish.generate("top", from_command(nested_3_levels))
    assert "__fish_seen_subcommand_from sub; and not __fish_seen_subcommand_from action" in script


def test_fish_uses_disable_description_for_boolean_negation():
    """uses Disable description for boolean negation"""
    script = Fish.generate("greet", from_command(simple_cmd))
    assert "-l no-loud" in script
    assert "-d 'Disable loud'" in script


def test_suppresses_default_file_completion_for_commands_without_path_arguments():
    """suppresses default file completion for commands without path arguments"""
    script = Fish.generate("server", from_command(with_subcommands))
    assert "complete -c server -n '__fish_use_subcommand' -f" in script
    assert "complete -c server -n '__fish_seen_subcommand_from start' -f" in script


def test_adds_a_entries_for_flags_so_they_appear_on_bare_tab():
    """adds -a entries for flags so they appear on bare TAB"""
    lines = Fish.generate("greet", from_command(simple_cmd)).split("\n")
    loud_arg = next(line for line in lines if "-a '--loud'" in line)
    assert 'not string match -q -- "-*" (commandline -ct)' in loud_arg
    assert "not __fish_contains_opt" in loud_arg
    times_arg = next(line for line in lines if "-a '--times'" in line)
    assert 'not string match -q -- "-*" (commandline -ct)' in times_arg
    assert any("-a '--no-loud'" in line for line in lines)


def test_bare_tab_a_entries_use_double_quotes_around_glob_pattern_to_avoid_nested_single_quote_errors():  # noqa: E501
    """bare-TAB -a entries use double quotes around glob pattern to avoid nested single-quote errors"""  # noqa: E501
    lines = Fish.generate("greet", from_command(simple_cmd)).split("\n")
    arg_entries = [line for line in lines if re.search(r"\s-a\s+'--", line)]
    assert len(arg_entries) > 0
    for line in arg_entries:
        assert '"-*"' in line
        assert "'-*'" not in line


def test_does_not_suppress_file_completion_for_commands_with_path_arguments():
    """does not suppress file completion for commands with path arguments"""
    lines = Fish.generate("process", from_command(with_paths)).split("\n")
    assert not any(re.fullmatch(r"complete -c process( -n '[^']*')? -f", line) for line in lines)


# --- PowerShell completions ----------------------------------------------------------


def test_registers_a_native_completer_with_a_context_per_subcommand_path():
    """registers a native completer with a context per subcommand path"""
    script = PowerShell.generate("top", from_command(nested_3_levels))
    assert "Register-ArgumentCompleter -Native -CommandName 'top'" in script
    assert "['sub'] = @{" in script
    assert "['sub action'] = @{" in script
    assert "@{ name = 'action'; description = 'Perform action' }" in script


def test_emits_flag_forms_choice_values_and_path_types():
    """emits flag forms, choice values and path types"""
    simple = PowerShell.generate("greet", from_command(simple_cmd))
    assert "forms = @('--loud', '-l'); takesValue = $false" in lines_with(simple, "name = 'loud'")
    assert "forms = @('--times'); takesValue = $true" in lines_with(simple, "name = 'times'")
    choices = PowerShell.generate("deploy", from_command(with_choices))
    assert "values = @('dev', 'staging', 'prod')" in choices
    assert "values = @('us-east', 'eu-west', 'ap-south')" in choices
    paths = PowerShell.generate("process", from_command(with_paths))
    assert "pathType = 'file'" in paths
    assert "pathType = 'directory'" in paths
    assert "[System.Management.Automation.CompletionCompleters]::CompleteFilename($typed)" in paths
    assert "$entry.pathType -eq 'directory' -and $file.ResultType -ne 'ProviderContainer'" in paths


def test_offers_only_positional_values_after_double_dash():
    """offers only positional values after --"""
    script = PowerShell.generate("server", from_command(with_subcommands))
    assert "if ($endOfOptions) { $position++; continue }" in script
    assert "if ($word -ceq '--') { $endOfOptions = $true; continue }" in script
    assert "if (-not $endOfOptions) {" in script


def test_does_not_treat_an_option_as_a_pending_flag_value():
    """does not treat an option as a pending flag value"""
    script = PowerShell.generate("server", from_command(with_subcommands))
    assert re.search(
        r"if \(\$flag\.takesValue\) \{\s+if \(-not \$isOption\) \{ continue \}", script
    )
    assert "if ($null -ne $pending -and $pending.takesValue -and -not $typedIsOption) {" in script


def test_completes_a_negative_number_as_a_value_not_a_flag():
    """completes a negative number as a value, not a flag"""
    script = PowerShell.generate("server", from_command(with_subcommands))
    assert "$typed.StartsWith('-')" not in script
    assert "if ($typedIsOption) {" in script


def test_offers_option_shaped_choices_only_where_the_cli_reads_them_as_values():
    """offers option-shaped choices only where the CLI reads them as values"""
    assert "& $optionLike $value" in PowerShell.generate("server", from_command(with_subcommands))


def test_tracks_used_flags_case_sensitively():
    """tracks used flags case-sensitively"""
    script = PowerShell.generate("server", from_command(with_subcommands))
    assert "$used = @{}" not in script
    assert "$used = [hashtable]::new([System.StringComparer]::Ordinal)" in script


def test_emits_non_ascii_text_as_char_code_units():
    """emits non-ASCII text as [char] code units"""
    script = PowerShell.generate("deploy", from_command(with_tricky_choices))
    assert re.search(r"[^\n\x20-\x7e]", script) is None
    assert "('a' + [char]0xD83D + [char]0xDE00 + 'b')" in script


def test_preserves_line_breaks_in_choice_values():
    """preserves line breaks in choice values"""

    class Tool(Config):
        mode = Flag.literals("mode", ["line\nbreak"])

    script = PowerShell.generate("tool", from_command(command.make("tool", Tool)))
    assert "values = @(('line' + [char]0x000A + 'break'))" in script


def test_escapes_values_for_single_quoted_power_shell_literals():
    """escapes values for single-quoted PowerShell literals"""
    script = PowerShell.generate("deploy", from_command(with_tricky_choices))
    assert "'it''s-fine'" in script
    assert "'foo'''" in script
    assert "'o''clock'" in script
    assert "'$HOME'" in script


def test_keeps_case_distinct_subcommand_contexts_and_emits_a_repeated_path_once():
    """keeps case-distinct subcommand contexts and emits a repeated path once"""
    script = PowerShell.generate(
        "tool",
        CommandDescriptor(
            "tool",
            None,
            subcommands=(leaf("config", "lower"), leaf("config", "lower"), leaf("Config", "upper")),
        ),
    )
    assert len(re.findall(r"\['config'\] = @\{", script)) == 1
    assert len(re.findall(r"\['Config'\] = @\{", script)) == 1
    assert len(re.findall(r"forms = @\('--lower'\)", script)) == 1
    assert len(re.findall(r"forms = @\('--upper'\)", script)) == 1


# --- Completions dispatcher ----------------------------------------------------------


def test_dispatches_to_bash_generator():
    """dispatches to bash generator"""
    script = Completions.generate("greet", "bash", from_command(simple_cmd))
    assert "complete -F _greet greet" in script


def test_dispatches_to_zsh_generator():
    """dispatches to zsh generator"""
    assert "#compdef greet" in Completions.generate("greet", "zsh", from_command(simple_cmd))


def test_dispatches_to_fish_generator():
    """dispatches to fish generator"""
    assert "complete -c greet" in Completions.generate("greet", "fish", from_command(simple_cmd))


def test_dispatches_to_powershell_generator():
    """dispatches to powershell generator"""
    script = Completions.generate("greet", "powershell", from_command(simple_cmd))
    assert "Register-ArgumentCompleter -Native -CommandName 'greet'" in script


class _Port(Config):
    port = Flag.integer("port")


def test_derives_a_zsh_script_from_a_command_tree_without_running_its_handlers():
    """derives a zsh script from a Command tree without running its handlers"""

    def handler(_: object) -> fx.Effect[None]:
        raise AssertionError("command handler should not run")

    cli = command.make("server", Config, handler).with_subcommands(
        command.make("start", _Port, handler)
    )

    descriptor = Completions.from_command(cli)
    assert [sub.name for sub in descriptor.subcommands] == ["start"]

    script = Completions.generate("server", "zsh", descriptor)
    assert "#compdef server" in script
    assert "_server_start()" in script
    assert "--port" in script


# --- Completions integration ---------------------------------------------------------


def test_generates_valid_bash_script_for_comprehensive_cli():
    """generates valid bash script for ComprehensiveCli"""
    script = Bash.generate("mycli", from_command(comprehensive_cli))
    for needle in [
        "_mycli()",
        "complete -F _mycli mycli",
        "--debug",
        "-d",
        "--quiet",
        "-q",
        "--config",
        "--no-debug",
        "--no-quiet",
        "_mycli_admin()",
        "_mycli_copy()",
        "_mycli_build()",
        "_mycli_git()",
        "_mycli_admin_users()",
        "_mycli_admin_config()",
        "_mycli_git_clone()",
        "_mycli_git_add()",
        "_mycli_git_status()",
        "_mycli_admin_users_list()",
        "_mycli_admin_users_create()",
        "_mycli_admin_config_set()",
        "_mycli_admin_config_get()",
    ]:
        assert needle in script


def test_generates_valid_zsh_script_for_comprehensive_cli():
    """generates valid zsh script for ComprehensiveCli"""
    script = Zsh.generate("mycli", from_command(comprehensive_cli))
    for needle in [
        "#compdef mycli",
        "_arguments",
        "_describe",
        "_mycli()",
        "--debug",
        "Enable debug logging",
        "--quiet",
        "_mycli_admin()",
        "_mycli_copy()",
        "_mycli_build()",
        "_mycli_git()",
        "_mycli_admin_users()",
        "_mycli_git_clone()",
        "_files",
    ]:
        assert needle in script


def test_generates_valid_fish_script_for_comprehensive_cli():
    """generates valid fish script for ComprehensiveCli"""
    script = Fish.generate("mycli", from_command(comprehensive_cli))
    for needle in [
        "complete -c mycli",
        "-a 'admin'",
        "-a 'copy'",
        "-a 'build'",
        "-a 'git'",
        "-l debug",
        "-s d",
        "-l quiet",
        "-s q",
        "-l no-debug",
        "-l no-quiet",
        "-d 'Administrative commands'",
        "-d 'Build the project'",
        "__fish_use_subcommand",
        "__fish_seen_subcommand_from admin",
        "__fish_seen_subcommand_from git",
    ]:
        assert needle in script


# --- Flags with an optional value ----------------------------------------------------


def test_do_not_take_the_next_word_as_the_flag_value():
    """do not take the next word as the flag value"""

    class App(Config):
        watch = (
            Flag.literals("watch", ["first-failure", "until-done"])
            .with_alias("w")
            .with_description("Watch mode")
            .with_optional_value("first-failure")
        )
        file = Argument.literals("file", ["one", "two"])

    descriptor = from_command(command.make("app", App))
    bash = Bash.generate("app", descriptor)
    assert "--watch|-w)\n" not in bash
    assert "--watch|-w) ;;" in bash
    assert "'(--watch -w)--watch=-[Watch mode]::value:(first-failure until-done)'" in Zsh.generate(
        "app", descriptor
    )
    assert "-a 'first-failure until-done'" not in Fish.generate("app", descriptor)
    assert "optionalValue = $true;" in PowerShell.generate("app", descriptor)


# --- Boolean flags with a custom or disabled negation --------------------------------


def test_advertise_the_configured_negation_name_and_never_the_default_no_flag_form():
    """advertise the configured negation name and never the default --no-<flag> form"""

    class App(Config):
        unsafe = (
            Flag.boolean("unsafe").with_description("Allow unsafe operations").without_negation()
        )
        validate = (
            Flag.boolean("validate")
            .with_description("Validate functions")
            .with_negation("skip-validate")
        )

    descriptor = from_command(command.make("app", App))
    for shell in ("bash", "zsh", "fish", "powershell"):
        script = Completions.generate("app", shell, descriptor)
        assert "--unsafe" in script, shell
        assert "no-unsafe" not in script, shell
        assert "skip-validate" in script, shell
        assert "no-validate" not in script, shell


def _replay_power_shell(descriptor: CommandDescriptor, line: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="pyfect-cli-pwsh-") as directory:
        file = Path(directory) / "replay.ps1"
        escaped = line.replace("'", "''")
        file.write_text(
            "\n".join(
                [
                    PowerShell.generate("app", descriptor),
                    f"$line = '{escaped}'",
                    "(TabExpansion2 -inputScript $line -cursorColumn $line.Length)"
                    ".CompletionMatches | ForEach-Object { $_.CompletionText }",
                ]
            )
        )
        output = run_program(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(file)], cwd=directory
        )
    return [text for text in _ESCAPES.sub("", output).replace("\r", "").split("\n") if text]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh is not installed")
def test_power_shell_replay_resolves_a_custom_negation_before_a_conflicting_alias():
    """PowerShell replay resolves a custom negation before a conflicting alias"""

    class App(Config):
        validate = Flag.boolean("validate").with_negation("skip")
        force = Flag.string("force").with_alias("skip")

    completions = _replay_power_shell(from_command(command.make("app", App)), "app --skip ")
    assert "--force" in completions
    assert "--validate" not in completions
