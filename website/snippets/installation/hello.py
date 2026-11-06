import pyfect as fx

hello = fx.succeed("world").map(lambda name: f"Hello, {name}!")

assert fx.run_blocking(hello) == "Hello, world!"
