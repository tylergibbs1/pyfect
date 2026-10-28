import pyfect as fx
from pyfect import console, layer, platform, testing
from pyfect.cli import Config, Flag, ShowHelp, command, prompt
from pyfect.cli.terminal_capabilities import Capabilities, TerminalCapabilities
from pyfect.errors import Done
from pyfect.queue import Queue
from pyfect.terminal import Terminal, TerminalService, UserInput, decode


class Init(Config):
    # Asked for when the flag is missing and the terminal can prompt.
    name = Flag.string("name").with_fallback_prompt(prompt.string("Project name"))


@fx.fn
def init(config: Init):
    template = yield from prompt.select(
        [prompt.Choice("Library", "lib"), prompt.Choice("Application", "app")],
        message="Template",
    )
    if (yield from prompt.confirm("Create it?", initial=True)):
        yield from console.log(f"created {config.name} from the {template} template")


cli = command.run_with(command.make("init", Init, init), version="1.0.0")


def user_types(keys: str):
    """A terminal whose user types `keys` (escape sequences for arrows)."""

    @fx.fn
    def make():
        queue = yield from Queue[UserInput, Done].unbounded()
        yield from queue.offer_all(decode(keys))
        return TerminalService(
            columns=fx.succeed(80),
            rows=fx.succeed(24),
            read_input=fx.succeed(queue),
            read_line=fx.succeed(""),
            display=lambda _text: fx.void,
        )

    prompts = Capabilities(can_color=False, can_animate=False, can_prompt=True)
    return layer.merge(layer.effect(Terminal, make()), layer.succeed(TerminalCapabilities, prompts))


def run(args: list[str], keys: str = ""):
    return cli(args).pipe(fx.provide(user_types(keys))).pipe(fx.provide(platform.layer))


DOWN = "\x1b[B"


@testing.effect
def test_prompts_for_what_the_flags_left_out():
    yield from run([], keys=f"demo\r{DOWN}\r\r")
    assert (yield from testing.log_lines) == ["created demo from the app template"]


@testing.effect
def test_a_flag_skips_its_prompt():
    yield from run(["--name", "demo"], keys="\rn")
    assert (yield from testing.log_lines) == []


@testing.effect
def test_a_typo_suggests_the_flag():
    error = yield from run(["--nmae", "demo"]).flip()
    assert isinstance(error, ShowHelp)
    printed = "\n".join(map(str, (yield from testing.error_lines)))
    assert "Did you mean this?\n    --name" in printed
