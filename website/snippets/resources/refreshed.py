import pyfect as fx

versions = iter(range(1, 100))


@fx.gen
def program():
    # Acquired once now; get reads the cached value until a refresh replaces it.
    config = yield from fx.Resource.manual(fx.sync(lambda: f"config v{next(versions)}"))
    before = yield from config.get()
    yield from config.refresh()
    after = yield from config.get()
    return before, after


assert fx.run_sync(fx.scoped(program)) == ("config v1", "config v2")
