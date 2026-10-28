import json

import pyfect as fx
from pyfect import console, platform
from pyfect.cli import Argument, Config, Flag, command


class Shared(Config):
    verbose = Flag.boolean("verbose").with_default(False).with_description("Explain each step")


class Add(Config):
    title = Argument.string("title").with_description("What to do")
    priority = (
        Flag.integer("priority").with_alias("p").with_default(1).with_description("1 (low) to 3")
    )


class List(Config):
    done = Flag.boolean("done").with_default(False).with_description("Include finished items")
    format = Flag.literals("format", ("text", "json")).with_default("text")


# The root command only holds the flags every subcommand shares.
todo = command.make("todo").with_shared_flags(Shared).with_description("Keep track of things")


@fx.fn
def add(config: Add):
    shared = yield from todo  # the parsed shared flags
    if shared.verbose:
        yield from console.log(f"priority {config.priority}")
    yield from console.log(f"added: {config.title}")


@fx.fn
def list_items(config: List):
    items = ["write docs", "ship it"] + (["plan release"] if config.done else [])
    text = json.dumps(items) if config.format == "json" else ", ".join(items)
    yield from console.log(text)


app = todo.with_subcommands(
    command.make("add", Add, add).with_description("Add an item"),
    command.make("list", List, list_items).with_description("List items"),
)

# `command.run(app, version=...)` reads sys.argv; `run_with` takes the arguments.
cli = command.run_with(app, version="1.0.0")
for args in (
    ["add", "write docs", "-p", "2", "--verbose"],
    ["list", "--done"],
    ["list", "--format", "json"],
):
    fx.run_main(cli(args).pipe(fx.provide(platform.layer)))
