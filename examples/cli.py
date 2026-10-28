"""A small command-line app: a ``todo`` tool with ``add`` and ``list``
subcommands sharing a ``--verbose`` flag. Try::

    python examples/cli.py --help
    python examples/cli.py add "write docs" --priority 2
    python examples/cli.py --verbose list --done --format json
"""

import json

import pyfect as fx
from pyfect import console, platform
from pyfect.cli import Argument, Config, Flag, command


class Shared(Config):
    verbose = Flag.boolean("verbose").with_default(False).with_description("Explain each step")


class Add(Config):
    title = Argument.string("title").with_description("What to do")
    priority = (
        Flag.integer("priority")
        .with_alias("p")
        .with_default(1)
        .with_description("1 (low) to 3 (high)")
    )


class List(Config):
    done = Flag.boolean("done").with_default(False).with_description("Include finished items")
    format = Flag.literals("format", ("text", "json")).with_default("text")


todo = command.make("todo").with_shared_flags(Shared).with_description("Keep track of things to do")


def add(config: Add):
    @fx.gen
    def body():
        shared = yield from todo
        if shared.verbose:
            yield from console.log(f"adding with priority {config.priority}")
        yield from console.log(f"added: {config.title}")

    return body


def list_items(config: List):
    @fx.gen
    def body():
        shared = yield from todo
        items = ["write docs", "ship it"] + (["plan release"] if config.done else [])
        if shared.verbose:
            yield from console.log(f"{len(items)} items")
        if config.format == "json":
            yield from console.log(json.dumps(items))
        else:
            for item in items:
                yield from console.log(f"- {item}")

    return body


app = todo.with_subcommands(
    command.make("add", Add, add).with_description("Add an item"),
    command.make("list", List, list_items).with_description("List items"),
)

main = command.run(app, version="1.0.0").pipe(fx.provide(platform.layer))

if __name__ == "__main__":
    fx.run_main(main)
