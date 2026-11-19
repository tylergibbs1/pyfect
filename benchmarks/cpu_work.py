"""Functions ``interpreter_pool.py`` runs in subinterpreters: they cross by
reference, so they live in a module a subinterpreter can import."""


def work(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i % 7
    return total


def stamp(_: int) -> float:
    import time

    return time.perf_counter()
