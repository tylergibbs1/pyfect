"""Effect's ``test/cli/completions/descriptor.test.ts``."""

from __future__ import annotations

from pyfect import schema as S
from pyfect.cli import Argument, Config, Flag, command
from pyfect.cli.completions._descriptor import Choice, PathKind, from_command


def test_extracts_command_name_and_description():
    """extracts command name and description"""
    desc = from_command(command.make("deploy").with_description("Deploy the application"))
    assert desc.name == "deploy"
    assert desc.description == "Deploy the application"


def test_extracts_string_flags_with_aliases():
    """extracts string flags with aliases"""

    class Test(Config):
        output = Flag.string("output").with_alias("o").with_description("Output directory")

    desc = from_command(command.make("test", Test))
    assert len(desc.flags) == 1
    assert desc.flags[0].name == "output"
    assert desc.flags[0].aliases == ("o",)
    assert desc.flags[0].description == "Output directory"
    assert desc.flags[0].type == "String"


def test_extracts_boolean_flags():
    """extracts boolean flags"""

    class Test(Config):
        verbose = Flag.boolean("verbose").with_alias("v")

    desc = from_command(command.make("test", Test))
    assert len(desc.flags) == 1
    assert desc.flags[0].name == "verbose"
    assert desc.flags[0].type == "Boolean"
    assert desc.flags[0].aliases == ("v",)


def test_extracts_integer_and_float_flags():
    """extracts integer and float flags"""

    class Test(Config):
        port = Flag.integer("port")
        ratio = Flag.finite("ratio")

    desc = from_command(command.make("test", Test))
    assert len(desc.flags) == 2
    types = {flag.name: flag.type for flag in desc.flags}
    assert types == {"port": "Int", "ratio": "Finite"}


def test_extracts_file_directory_and_path_flags():
    """extracts file, directory, and path flags"""

    class Test(Config):
        input = Flag.file("input")
        out_dir = Flag.directory("out-dir")
        config = Flag.path("config", path_type="either")

    desc = from_command(command.make("test", Test))
    types = {flag.name: flag.type for flag in desc.flags}
    assert types == {
        "input": PathKind("file"),
        "out-dir": PathKind("directory"),
        "config": PathKind("either"),
    }


def test_retains_path_semantics_when_a_path_has_a_custom_metavar():
    """retains path semantics when a path has a custom metavar"""

    class App(Config):
        directory = Flag.path("directory", path_type="directory", type_name="DIR")
        file = Argument.path("file", path_type="file").with_metavar("INPUT")

    descriptor = from_command(command.make("app", App))
    assert descriptor.flags[0].type == PathKind("directory")
    assert descriptor.arguments[0].type == PathKind("file")


def test_classifies_file_backed_flags_and_arguments_as_file_paths():
    """classifies file-backed flags and arguments as file paths"""

    class App(Config):
        flag_text = Flag.file_text("flag-text")
        flag_parse = Flag.file_parse("flag-parse")
        flag_schema = Flag.file_schema("flag-schema", S.Unknown)
        argument_text = Argument.file_text("argument-text")
        argument_parse = Argument.file_parse("argument-parse")
        argument_schema = Argument.file_schema("argument-schema", S.Unknown)

    descriptor = from_command(command.make("app", App))
    file_type = PathKind("file")
    assert [flag.type for flag in descriptor.flags] == [file_type] * 3
    assert [argument.type for argument in descriptor.arguments] == [file_type] * 3


def test_extracts_choice_flags_with_values():
    """extracts choice flags with values"""

    class Test(Config):
        color = Flag.literals("color", ["red", "green", "blue"])

    desc = from_command(command.make("test", Test))
    assert len(desc.flags) == 1
    assert desc.flags[0].type == Choice(("red", "green", "blue"))


def test_extracts_optional_flags():
    """extracts optional flags"""

    class Test(Config):
        name = Flag.string("name").optional()

    desc = from_command(command.make("test", Test))
    assert len(desc.flags) == 1
    assert desc.flags[0].name == "name"
    assert desc.flags[0].type == "String"


def test_extracts_positional_arguments_with_types():
    """extracts positional arguments with types"""

    class Test(Config):
        name = Argument.string("name")
        count = Argument.integer("count")

    desc = from_command(command.make("test", Test))
    assert len(desc.arguments) == 2
    by_name = {argument.name: argument for argument in desc.arguments}
    assert by_name["name"].type == "String"
    assert by_name["count"].type == "Int"
    assert by_name["name"].required is True
    assert by_name["count"].required is True


def test_extracts_variadic_arguments():
    """extracts variadic arguments"""

    class Test(Config):
        files = Argument.string("files").variadic(min=1)

    desc = from_command(command.make("test", Test))
    assert len(desc.arguments) == 1
    assert desc.arguments[0].name == "files"
    assert desc.arguments[0].variadic is True
    assert desc.arguments[0].required is True


def test_extracts_optional_arguments():
    """extracts optional arguments"""

    class Test(Config):
        email = Argument.string("email").optional()

    desc = from_command(command.make("test", Test))
    assert len(desc.arguments) == 1
    assert desc.arguments[0].name == "email"
    assert desc.arguments[0].required is False


def test_extracts_nested_subcommands_recursively():
    """extracts nested subcommands recursively"""
    leaf = command.make("leaf").with_description("A leaf command")
    mid = command.make("mid").with_subcommands(leaf)
    desc = from_command(command.make("root").with_subcommands(mid))
    assert len(desc.subcommands) == 1
    assert desc.subcommands[0].name == "mid"
    assert len(desc.subcommands[0].subcommands) == 1
    assert desc.subcommands[0].subcommands[0].name == "leaf"
    assert desc.subcommands[0].subcommands[0].description == "A leaf command"


def test_extracts_descriptions_from_flags_and_arguments():
    """extracts descriptions from flags and arguments"""

    class Test(Config):
        port = Flag.integer("port").with_description("Port number")
        host = Argument.string("host").with_description("Hostname")

    desc = from_command(command.make("test", Test))
    assert desc.flags[0].description == "Port number"
    assert desc.arguments[0].description == "Hostname"


def test_handles_commands_with_no_flags_or_arguments():
    """handles commands with no flags or arguments"""
    desc = from_command(command.make("noop"))
    assert desc.name == "noop"
    assert desc.flags == ()
    assert desc.arguments == ()
    assert desc.subcommands == ()


def test_handles_deeply_nested_command_trees():
    """handles deeply nested command trees"""

    class Level3(Config):
        flag = Flag.boolean("deep")

    level2 = command.make("level2").with_subcommands(command.make("level3", Level3))
    level1 = command.make("level1").with_subcommands(level2)
    desc = from_command(command.make("root").with_subcommands(level1))
    deep = desc.subcommands[0].subcommands[0].subcommands[0]
    assert deep.name == "level3"
    assert len(deep.flags) == 1
    assert deep.flags[0].name == "deep"
    assert deep.flags[0].type == "Boolean"


def test_extracts_choice_arguments():
    """extracts choice arguments"""

    class Test(Config):
        env = Argument.literals("env", ["dev", "staging", "prod"])

    desc = from_command(command.make("test", Test))
    assert len(desc.arguments) == 1
    assert desc.arguments[0].type == Choice(("dev", "staging", "prod"))


def test_extracts_file_directory_arguments():
    """extracts file/directory arguments"""

    class Test(Config):
        input = Argument.file("input", must_exist=False)
        out_dir = Argument.directory("output", must_exist=False)

    desc = from_command(command.make("test", Test))
    types = {argument.name: argument.type for argument in desc.arguments}
    assert types == {"input": PathKind("file"), "output": PathKind("directory")}


def test_extracts_multiple_subcommands():
    """extracts multiple subcommands"""
    root = command.make("root").with_subcommands(
        command.make("alpha").with_description("First"),
        command.make("beta").with_description("Second"),
        command.make("gamma").with_description("Third"),
    )
    assert [sub.name for sub in from_command(root).subcommands] == ["alpha", "beta", "gamma"]


def test_prefers_short_descriptions_for_subcommand_listings():
    """prefers short descriptions for subcommand listings"""
    build = (
        command.make("build")
        .with_description("Build the project and all artifacts")
        .with_short_description("Build artifacts")
    )
    test = command.make("test").with_description("Run the full test suite")
    desc = from_command(command.make("root").with_subcommands(build, test))
    assert desc.subcommands[0].description == "Build artifacts"
    assert desc.subcommands[1].description == "Run the full test suite"
