import pyfect as fx


@fx.gen
def crunch():
    yield from fx.sleep("10 millis").forever()


@fx.gen
def program():
    # The timeout interrupts the effect on the other thread and waits for its
    # finalizer before it fails.
    work = fx.on_thread(crunch.ensuring(fx.sync(lambda: print("cleaned up on the worker thread"))))
    ex = yield from work.timeout("50 millis").exit()
    print("exit:", type(ex).__name__)


fx.run_blocking(program)
