import pyfect as fx
from pyfect import console, platform
from pyfect.cli import Argument, Config, Flag, ShowHelp, command
from pyfect.cli.help_doc import ExampleDoc


class Deploy(Config):
    service = Argument.string("service").with_description("The service to deploy")
    env = Flag.literals("env", ("staging", "prod")).with_default("staging")
    replicas = Flag.integer("replicas").with_alias("r").with_default(2).with_description("How many")
    force = Flag.boolean("force").with_default(False).with_description("Skip the checks")


deploy = (
    command.make("deploy", Deploy, lambda c: console.log(f"deploying {c.service} to {c.env}"))
    .with_description("Deploy a service")
    .with_examples([ExampleDoc("deploy api --env prod -r 3", "Three replicas in production")])
)

cli = command.run_with(deploy, version="1.0.0")
# Showing help ends the program with ShowHelp (exit code 0); catch it to carry on.
shown = cli(["--help"]).pipe(fx.catch_tag(ShowHelp, lambda _: fx.void))
fx.run_main(shown.pipe(fx.provide(platform.layer)))
