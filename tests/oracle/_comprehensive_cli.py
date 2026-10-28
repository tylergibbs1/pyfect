"""Effect's ``test/cli/fixtures/ComprehensiveCli.ts``: a command tree with
every kind of param, nested subcommands and shared flags. Handlers log
what they parsed through ``TestActions``, with Effect's detail keys."""

from __future__ import annotations

from collections.abc import Sequence

import pyfect as fx
from pyfect.cli import Argument, Config, Flag, command, nested

from ._cli_env import log_action

# --- admin users ---------------------------------------------------------------------


class UsersList(Config):
    format = (
        Flag.string("format")
        .with_description("Output format (json, table, csv)")
        .with_default("table")
    )
    active = Flag.boolean("active").with_description("Show only active users").with_default(False)
    verbose = (
        Flag.boolean("verbose")
        .with_alias("v")
        .with_description("Show detailed information")
        .with_default(False)
    )


users_list = command.make(
    "list",
    UsersList,
    lambda c: log_action(
        "users list", {"format": c.format, "active": c.active, "verbose": c.verbose}
    ),
).with_description("List all users in the system")


class UsersCreate(Config):
    username = Argument.string("username").with_description("Username for the new user")
    email = Argument.string("email").with_description("Email address (optional)").optional()
    role = Flag.string("role").with_description("User role (admin, user, guest)")
    notify = (
        Flag.boolean("notify")
        .with_alias("n")
        .with_description("Send notification email")
        .with_default(False)
    )


users_create = command.make(
    "create",
    UsersCreate,
    lambda c: log_action(
        "users create",
        {"username": c.username, "email": c.email, "role": c.role, "notify": c.notify},
    ),
).with_description("Create a new user account")

users = (
    command.make("users")
    .with_description("User management commands")
    .with_subcommands(users_list, users_create)
)

# --- admin config --------------------------------------------------------------------


class ConfigSet(Config):
    pairs = (
        Argument.string("key=value")
        .with_description("Configuration key-value pairs")
        .variadic(min=1)
    )
    file = (
        Flag.file("config-file")
        .with_alias("f")
        .with_description("Write to specific config file")
        .optional()
    )


config_set = command.make(
    "set", ConfigSet, lambda c: log_action("config set", {"pairs": c.pairs, "file": c.file})
).with_description("Set configuration values")


class ConfigGet(Config):
    key = Argument.string("key").with_description("Configuration key to retrieve")
    source = (
        Flag.string("source")
        .with_description("Configuration source (local, global, system)")
        .with_default("local")
    )


config_get = command.make(
    "get", ConfigGet, lambda c: log_action("config get", {"key": c.key, "source": c.source})
).with_description("Get configuration value")


class ConfigShared(Config):
    profile = (
        Flag.string("profile")
        .with_alias("p")
        .with_description("Configuration profile to use")
        .optional()
    )


config = (
    command.make("config")
    .with_shared_flags(ConfigShared)
    .with_description("Manage application configuration")
    .with_subcommands(config_set, config_get)
)


class AdminShared(Config):
    sudo = Flag.boolean("sudo").with_description("Run with elevated privileges").with_default(False)


admin = (
    command.make("admin")
    .with_shared_flags(AdminShared)
    .with_description("Administrative commands")
    .with_subcommands(users, config)
)

# --- file operations -----------------------------------------------------------------


class Copy(Config):
    source = Argument.file("source", must_exist=False).with_description("Source file or directory")
    destination = Argument.file("destination", must_exist=False).with_description(
        "Destination path"
    )
    recursive = (
        Flag.boolean("recursive")
        .with_alias("r")
        .with_description("Copy directories recursively")
        .with_default(False)
    )
    force = (
        Flag.boolean("force")
        .with_alias("f")
        .with_description("Overwrite existing files")
        .with_default(False)
    )
    buffer = Flag.integer("buffer-size").with_description("Buffer size in KB").with_default(64)


copy = command.make(
    "copy",
    Copy,
    lambda c: log_action(
        "copy",
        {
            "source": c.source,
            "destination": c.destination,
            "recursive": c.recursive,
            "force": c.force,
            "bufferSize": c.buffer,
        },
    ),
).with_description("Copy files or directories")


class Move(Config):
    paths = (
        Argument.string("paths").with_description("Source path(s) and destination").variadic(min=2)
    )
    interactive = (
        Flag.boolean("interactive")
        .with_alias("i")
        .with_description("Prompt before overwrite")
        .with_default(False)
    )


move = command.make(
    "move",
    Move,
    lambda c: log_action("move", {"paths": c.paths, "interactive": c.interactive}),
).with_description("Move or rename files")


class Remove(Config):
    files = Argument.string("files").with_description("Files to remove").variadic(min=1)
    recursive = (
        Flag.boolean("recursive")
        .with_alias("r")
        .with_description("Remove directories and contents")
        .with_default(False)
    )
    force = (
        Flag.boolean("force")
        .with_alias("f")
        .with_description("Force removal without prompts")
        .with_default(False)
    )
    verbose = (
        Flag.boolean("verbose")
        .with_alias("v")
        .with_description("Explain what is being done")
        .with_default(False)
    )


remove = command.make(
    "remove",
    Remove,
    lambda c: log_action(
        "remove",
        {"files": c.files, "recursive": c.recursive, "force": c.force, "verbose": c.verbose},
    ),
).with_description("Remove files or directories")


class Build(Config):
    output = Flag.string("output").with_alias("o").with_description("Output directory")
    verbose = (
        Flag.boolean("verbose")
        .with_alias("v")
        .with_description("Enable verbose output")
        .with_default(False)
    )
    config_file = (
        Flag.string("config-file")
        .with_alias("f")
        .with_description("Configuration file path")
        .optional()
    )


build = command.make(
    "build",
    Build,
    lambda c: log_action(
        "build",
        {
            "output": c.output,
            "verbose": c.verbose,
            "config": "none" if c.config_file is None else c.config_file,
        },
    ),
).with_description("Build the project")

# --- git -----------------------------------------------------------------------------


class GitClone(Config):
    repository = Argument.string("repository").with_description("Repository URL or path")
    branch = Flag.string("branch").with_default("main").with_description("Branch to clone")


git_clone = command.make(
    "clone",
    GitClone,
    lambda c: log_action("git clone", {"repository": c.repository, "branch": c.branch}),
).with_description("Clone a repository")


class GitAdd(Config):
    files = Argument.string("files").with_description("Files to add")
    update = Flag.boolean("update").with_description("Update tracked files").with_default(False)


git_add = command.make(
    "add", GitAdd, lambda c: log_action("git add", {"files": c.files, "update": c.update})
).with_description("Add files to staging")


class GitStatus(Config):
    short = Flag.boolean("short").with_description("Show short format").with_default(False)


git_status = command.make(
    "status", GitStatus, lambda c: log_action("git status", {"short": c.short})
).with_description("Show repository status")


class GitShared(Config):
    verbose = Flag.boolean("verbose").with_description("Enable verbose output").with_default(False)


git = (
    command.make("git")
    .with_shared_flags(GitShared)
    .with_handler(lambda c: log_action("git", {"verbose": c.verbose}))
    .with_description("Git version control")
    .with_subcommands(git_clone, git_add, git_status)
)

# --- error handling ------------------------------------------------------------------


class TestRequired(Config):
    __test__ = False

    required = Flag.string("required").with_description("A required option for testing")


test_required = command.make(
    "test-required", TestRequired, lambda c: log_action("test-required", {"required": c.required})
).with_description("Test command with required option")


class TestFailing(Config):
    __test__ = False

    input = Flag.string("input").with_description("Input that will cause handler to fail")


def _failing(c: TestFailing):
    return log_action("test-failing", {"input": c.input}).and_then(fx.fail("Handler error"))


test_failing = command.make("test-failing", TestFailing, _failing).with_description(
    "Test command that always fails"
)

# --- deploy --------------------------------------------------------------------------


class Database(Config):
    host = Flag.string("db-host").with_description("Database host")
    port = Flag.integer("db-port").with_description("Database port")


class Deploy(Config):
    service = Argument.string("service").with_description("Service to deploy")
    environment = Argument.string("environment").with_description("Target environment")
    database = nested(Database)
    dry_run = Flag.boolean("dry-run").with_description("Perform a dry run").with_default(False)


deploy_command = command.make(
    "deploy",
    Deploy,
    lambda c: log_action(
        "deploy",
        {
            "service": c.service,
            "environment": c.environment,
            "database": {"host": c.database.host, "port": c.database.port},
            "dryRun": c.dry_run,
        },
    ),
).with_description("Deploy a service")


class AppShared(Config):
    env = Flag.string("env").with_description("Environment setting").optional()


app = (
    command.make("app")
    .with_shared_flags(AppShared)
    .with_handler(lambda c: log_action("app", {"env": c.env}))
    .with_description("Application management")
    .with_subcommands(deploy_command)
)


class ServiceShared(Config):
    name = Flag.string("name").with_description("Service name")


service_command = (
    command.make("service")
    .with_shared_flags(ServiceShared)
    .with_handler(lambda c: log_action("service", {"name": c.name}))
    .with_description("Service management")
    .with_subcommands(deploy_command)
)


class AppNestedShared(Config):
    env = Flag.string("env").with_description("Environment setting")


app_with_service = (
    command.make("app-nested")
    .with_shared_flags(AppNestedShared)
    .with_handler(lambda c: log_action("app-nested", {"env": c.env}))
    .with_description("Application with nested services")
    .with_subcommands(service_command)
)

# --- root ----------------------------------------------------------------------------


class Global(Config):
    debug = (
        Flag.boolean("debug")
        .with_alias("d")
        .with_description("Enable debug logging")
        .with_default(False)
    )
    config = (
        Flag.file("config")
        .with_alias("c")
        .with_description("Path to configuration file")
        .optional()
    )
    quiet = (
        Flag.boolean("quiet")
        .with_alias("q")
        .with_description("Suppress non-error output")
        .with_default(False)
    )


comprehensive_cli = (
    command.make("mycli")
    .with_shared_flags(Global)
    .with_description("A comprehensive CLI tool demonstrating all features")
    .with_subcommands(
        admin,
        copy,
        move,
        remove,
        build,
        git,
        test_required,
        test_failing,
        app,
        app_with_service,
    )
)

_runner = command.run_with(comprehensive_cli, version="1.0.0")


def run(args: Sequence[str]):
    return _runner(args)
