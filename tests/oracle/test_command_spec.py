"""Ports of Effect's ``cli/CommandSpec.test.ts``, every title. Each test's
docstring is the Effect test title.

``CommandSpec.resolve(app, path, { builtIns })`` is
``command_spec.resolve(app, path, built_ins=...)``, which gives ``None`` for an
unknown path where Effect's gives ``Option.none()``. A flag's ``typeName`` is
``type_name``, its ``_tag``-union type and scope are dataclasses
(``PlainType("Int")``, ``Local()``), and fallbacks are ``param``'s
``DefaultFallback(value)``, ``DefaultEffectFallback()``, ``ConfigFallback()``
and ``PromptFallback()``. A config class lists its flags in field order.
"""

from typing import Any

import pyfect as fx
from pyfect import config as config_
from pyfect.cli import Action, Argument, Config, Flag, Setting, command, group, prompt
from pyfect.cli import command_spec as spec_
from pyfect.cli.command_spec import (
    ChoiceType,
    Global,
    Inherited,
    Local,
    PlainType,
    Spec,
    Subcommand,
    VariadicBounds,
)
from pyfect.cli.global_flag import GlobalFlag
from pyfect.cli.global_flag import Version as VersionFlag
from pyfect.cli.help_doc import ExampleDoc
from pyfect.cli.param import (
    ConfigFallback,
    DefaultEffectFallback,
    DefaultFallback,
    PromptFallback,
)
from pyfect.context import Tag


def spec_of(app: Any, path: list[str], built_ins: list[GlobalFlag] | None = None) -> Spec:
    found = spec_.resolve(app, path, built_ins=built_ins)
    assert found is not None
    return found


def flag_of(spec: Spec, name: str) -> spec_.Flag:
    found = next((flag for flag in spec.flags if flag.name == name), None)
    assert found is not None, f"flag --{name} not found"
    return found


def argument_of(spec: Spec, name: str) -> spec_.Argument:
    found = next((argument for argument in spec.arguments if argument.name == name), None)
    assert found is not None, f"argument <{name}> not found"
    return found


def test_resolves_a_command_by_its_name_path_and_returns_none_for_unknown_paths() -> None:
    """resolves a command by its name path and returns none for unknown paths"""
    push = command.make("push").with_description("Push migrations")
    db = command.make("db").with_alias("database").with_subcommands(push)
    app = command.make("app").with_subcommands(db)

    spec = spec_of(app, ["app", "db", "push"])
    assert spec.path == ("app", "db", "push")
    assert spec.name == "push"
    assert spec.description == "Push migrations"
    # The root command resolves to itself.
    assert spec_of(app, ["app"]).name == "app"
    # Paths are canonical names only: aliases, unknown segments, a foreign root and the
    # empty path are all rejected instead of resolving to the deepest matching ancestor.
    assert spec_.resolve(app, ["app", "database", "push"]) is None
    assert spec_.resolve(app, ["app", "db", "pull"]) is None
    assert spec_.resolve(app, ["other", "db"]) is None
    assert spec_.resolve(app, []) is None


class _Region(Setting[str | None]):
    flag = Flag.string("region").optional()


def test_reports_the_effective_flags_of_a_path_with_their_provenance() -> None:
    """reports the effective flags of a path with their provenance"""

    class Leaf(Config):
        topic = Flag.string("topic")

    class Profile(Config):
        profile = Flag.string("profile")

    class App(Profile):
        workspace = Flag.string("workspace")

    leaf = command.make("leaf", Leaf)
    admin = command.make("admin").pipe(command.with_global_flags(_Region)).with_subcommands(leaf)
    app = command.make("app", App).with_shared_flags(Profile).with_subcommands(admin)

    spec = spec_of(app, ["app", "admin", "leaf"])
    # Local first, then inherited shared flags root to leaf, then globals with built-ins
    # ahead of declarations. Flags local to an ancestor are not part of the leaf's surface.
    assert [(flag.name, flag.scope) for flag in spec.flags] == [
        ("topic", Local()),
        ("profile", Inherited(("app",))),
        ("help", Global(None, "Action")),
        ("version", Global(None, "Action")),
        ("wizard", Global(None, "Action")),
        ("completions", Global(None, "Action")),
        ("log-level", Global(None, "Setting")),
        ("region", Global(("app", "admin"), "Setting")),
    ]
    # Built-ins come from the options and default to the built-in global flags.
    without = spec_of(app, ["app", "admin", "leaf"], built_ins=[])
    assert [flag.name for flag in without.flags] == ["topic", "profile", "region"]
    # A global declared on a descendant is not active on its ancestors.
    assert all(flag.name != "region" for flag in spec_of(app, ["app"]).flags)


def test_includes_hidden_flags_and_unlisted_subcommands_and_marks_them() -> None:
    """includes hidden flags and unlisted subcommands and marks them"""

    class App(Config):
        debug_port = Flag.integer("debug-port").with_hidden()
        verbose = Flag.boolean("verbose")

    secret = command.make("experimental-foo").with_unlisted()
    deploy = (
        command.make("deploy")
        .with_alias("d")
        .with_short_description("Deploy")
        .with_description("Deploy the application")
    )
    app = command.make("app", App).with_subcommands(group("Ops", deploy), secret)

    spec = spec_of(app, ["app"], built_ins=[])
    assert [(flag.name, flag.hidden) for flag in spec.flags] == [
        ("debug-port", True),
        ("verbose", False),
    ]
    # Same order as help: ungrouped subcommands first, then groups in declaration order.
    # An aliased subcommand is listed once, with its alias as data.
    assert spec.subcommands == (
        Subcommand("experimental-foo", None, None, True, None, None),
        Subcommand("deploy", "d", "Ops", False, "Deploy", "Deploy the application"),
    )


def test_describes_the_input_surface_of_a_flag_without_collapsing_types() -> None:
    """describes the input surface of a flag without collapsing types"""

    class App(Config):
        port = (
            Flag.integer("port")
            .with_alias("p")
            .with_description("Port to listen on")
            .with_metavar("PORT")
        )
        config = Flag.file_text("config")
        format = Flag.literals("format", ("json", "table"))
        force = Flag.boolean("force")
        dry_run = Flag.boolean("dry-run").with_default(False)
        quiet = Flag.boolean("quiet").without_negation()
        color = Flag.string("color").with_optional_value("auto")

    spec = spec_of(command.make("app", App), ["app"], built_ins=[])

    port = flag_of(spec, "port")
    assert port.aliases == ("p",)
    assert port.description == "Port to listen on"
    assert port.type == PlainType("Int")
    assert port.type_name == "integer"
    assert port.metavar == "PORT"
    assert port.required
    assert port.fallbacks == ()
    assert flag_of(spec, "config").type == PlainType("FileText")
    assert flag_of(spec, "format").type == ChoiceType(("json", "table"))
    # A bare boolean flag fails with MissingOption when omitted, like any other flag;
    # only a fallback makes it optional. Help's display rule is not the parser's rule.
    force = flag_of(spec, "force")
    assert force.required
    assert force.negation == "no-force"
    assert not flag_of(spec, "dry-run").required
    assert flag_of(spec, "quiet").negation is None
    assert flag_of(spec, "color").optional_value == "auto"


def test_records_fallbacks_structurally_in_the_order_they_are_consulted() -> None:
    """records fallbacks structurally in the order they are consulted, without executing them"""
    evaluated: list[str] = []

    def default_retries() -> int:
        evaluated.append("default")
        return 3

    def name_prompt() -> prompt.Prompt[str]:
        evaluated.append("prompt")
        return prompt.string("Name")

    class App(Config):
        port = Flag.integer("port").with_fallback_config(config_.integer("PORT")).with_default(8080)
        token = Flag.string("token").with_fallback_config(config_.string("TOKEN"))
        retries = Flag.integer("retries").with_default(fx.sync(default_retries))
        name = Flag.string("name").with_fallback_prompt(fx.sync(name_prompt))
        tag = Flag.string("tag").optional()

    spec = spec_of(command.make("app", App), ["app"], built_ins=[])

    port = flag_of(spec, "port")
    assert not port.required
    assert port.fallbacks == (ConfigFallback(), DefaultFallback(8080))
    # A config fallback alone does not make the flag optional on the command line.
    token = flag_of(spec, "token")
    assert token.required
    assert token.fallbacks == (ConfigFallback(),)
    assert flag_of(spec, "retries").fallbacks == (DefaultEffectFallback(),)
    assert flag_of(spec, "name").fallbacks == (PromptFallback(),)
    assert evaluated == []
    tag = flag_of(spec, "tag")
    assert not tag.required
    assert tag.fallbacks == ()


class _EnvVar(Tag[str], key="effect/test/cli/CommandSpec/EnvVar"):
    pass


def test_carries_user_annotations_and_keeps_metadata_through_later_combinators() -> None:
    """carries user annotations and keeps metadata through later combinators"""

    class App(Config):
        port = (
            Flag.integer("port")
            .with_default(8080)
            .annotate(_EnvVar, "APP_PORT")
            .with_alias("p")
            .with_metavar("PORT")
        )
        plain = Flag.string("plain")

    spec = spec_of(command.make("app", App), ["app"], built_ins=[])

    port = flag_of(spec, "port")
    assert port.annotations.get_unsafe(_EnvVar) == "APP_PORT"
    assert port.fallbacks == (DefaultFallback(8080),)
    assert port.aliases == ("p",)
    assert port.metavar == "PORT"
    assert flag_of(spec, "plain").annotations.get_option(_EnvVar) is None


def test_reports_argument_requiredness_and_variadic_bounds() -> None:
    """reports argument requiredness and variadic bounds"""

    class App(Config):
        target = Argument.string("target")
        files = Argument.string("files").variadic()
        names = Argument.string("names").at_least(1)

    spec = spec_of(command.make("app", App), ["app"], built_ins=[])

    target = argument_of(spec, "target")
    assert target.required
    assert target.variadic is None
    # A zero-minimum variadic accepts no values, so it is not required.
    files = argument_of(spec, "files")
    assert not files.required
    assert files.variadic == VariadicBounds(None, None)
    names = argument_of(spec, "names")
    assert names.required
    assert names.variadic == VariadicBounds(1, None)


def test_reports_each_alternative_branch_with_the_wrappers_on_its_own_path() -> None:
    """reports each alternative branch with the wrappers on its own path"""

    class App(Config):
        config = Flag.string("config").or_else(
            lambda: Flag.string("config-url").with_default("https://example.com/config")
        )
        output = (
            Flag.string("output").with_default("stdout").or_else(lambda: Flag.string("output-file"))
        )
        format = (
            Flag.string("format").or_else(lambda: Flag.string("format-file")).with_default("json")
        )

    spec = spec_of(command.make("app", App), ["app"], built_ins=[])

    # Metadata is branch-local: a wrapper describes the singles beneath it and nothing else.
    config = flag_of(spec, "config")
    assert config.required
    assert config.fallbacks == ()
    config_url = flag_of(spec, "config-url")
    assert not config_url.required
    assert config_url.fallbacks == (DefaultFallback("https://example.com/config"),)
    # A default on the main branch is not copied onto the alternative.
    assert flag_of(spec, "output").fallbacks == (DefaultFallback("stdout"),)
    output_file = flag_of(spec, "output-file")
    assert output_file.required
    assert output_file.fallbacks == ()
    # A wrapper outside the alternation applies to every branch.
    for name in ["format", "format-file"]:
        flag = flag_of(spec, name)
        assert not flag.required, name
        assert flag.fallbacks == (DefaultFallback("json"),)


def test_derives_omission_from_wrappers_outside_a_variadic_never_from_per_item_ones() -> None:
    """derives omission from wrappers outside a variadic, never from per-item ones"""

    class App(Config):
        files = Argument.string("files").with_default("README.md").at_least(1)
        tags = Flag.string("tag").with_default("untagged").at_least(1)
        names = Argument.string("names").at_least(1).with_default(("anonymous",))

    spec = spec_of(command.make("app", App), ["app"], built_ins=[])

    # A per-item default inside the variadic does not satisfy the outer minimum.
    files = argument_of(spec, "files")
    assert files.required
    assert files.fallbacks == ()
    assert files.variadic == VariadicBounds(1, None)
    tags = flag_of(spec, "tag")
    assert tags.required
    assert tags.fallbacks == ()
    # A default applied outside the variadic does satisfy omission.
    names = argument_of(spec, "names")
    assert not names.required
    assert names.fallbacks == (DefaultFallback(("anonymous",)),)
    assert names.variadic == VariadicBounds(1, None)


class _RequiredRegion(Setting[str]):
    flag = Flag.string("region")


def test_never_reports_an_action_global_as_required() -> None:
    """never reports an Action global as required"""
    print_ = Action(Flag.string("print"), lambda _value, _context: fx.void)
    app = command.make("app").pipe(command.with_global_flags(print_, _RequiredRegion))

    spec = spec_of(app, ["app"], built_ins=[])

    # The runner parses an Action only when it is present on the command line, but parses
    # every Setting on every run.
    assert not flag_of(spec, "print").required
    assert flag_of(spec, "region").required


def test_keeps_an_active_global_flag_whose_name_a_local_flag_shadows() -> None:
    """keeps an active global flag whose name a local flag shadows"""

    class Release(Config):
        version = Flag.string("version")

    app = command.make("app").with_subcommands(command.make("release", Release))

    spec = spec_of(app, ["app", "release"], built_ins=[VersionFlag])

    # Globals are deduplicated by identity only, as in help, so both entries remain and a
    # generator can still document `-v`.
    assert [(flag.name, type(flag.scope).__name__, flag.aliases) for flag in spec.flags] == [
        ("version", "Local", ()),
        ("version", "Global", ("v",)),
    ]


def test_resolves_examples_for_the_requested_path() -> None:
    """resolves examples for the requested path"""
    deploy = command.make("deploy").with_examples(
        lambda path: [ExampleDoc(f"{' '.join(path)} --prod", "Deploy to production")]
    )
    app = command.make("app").with_subcommands(deploy)

    assert spec_of(app, ["app", "deploy"]).examples == (
        ExampleDoc("app deploy --prod", "Deploy to production"),
    )
