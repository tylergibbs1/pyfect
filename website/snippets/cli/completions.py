import pyfect as fx
from pyfect import platform
from pyfect.cli import Argument, Config, Flag, command


class Deploy(Config):
    service = Argument.string("service").with_description("What to deploy")
    env = Flag.literals("env", ("staging", "prod")).with_description("Where to deploy")


app = command.make("ship").with_subcommands(
    command.make("deploy", Deploy, lambda _: fx.void).with_description("Deploy a service")
)

# What `ship --completions fish` prints; "powershell" (or "pwsh"), "bash" and "zsh" work too.
cli = command.run_with(app, version="1.0.0")
fx.run_main(cli(["--completions", "fish"]).pipe(fx.provide(platform.layer)))
