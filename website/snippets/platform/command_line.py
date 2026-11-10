import pyfect as fx
from pyfect import platform, process, redacted
from pyfect.process import ChildProcessSpawner, CommandLineError, command_line


@fx.fn
def program():
    spawner = yield from ChildProcessSpawner()

    # A template is written as in a shell: quotes group words, and each value
    # is one literal argument, whatever it contains.
    message = "fix: a | b; $HOME"
    echo = process.make(["printf '%s\\n' ", ' "two  words"'], message)
    print((yield from spawner.string(echo)), end="")

    # Text that needs a shell is refused where the command is made.
    try:
        process.make(["ls *.txt | wc -l"])
    except CommandLineError as error:
        print(error.reason, "-", error.message)

    # A script for a shell: build it with command_line.join, then run it with shell=True.
    script = command_line.join(["printf", "%s|", "a b", "it's"]).get_or_raise()
    print(script)
    print((yield from spawner.string(process.make(script, shell=True))))

    # Redacted arguments reach the process but never logs or errors.
    token = redacted.make("hunter2")
    print(command_line.display(["curl", "-H", token, "https://example.com/a b"]))


fx.run_main(fx.scoped(program()).pipe(fx.provide(platform.layer)))
