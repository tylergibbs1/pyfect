import threading

import pyfect as fx

requests = fx.Ref(0)
stock = fx.TxRef(1000)
sold = fx.TxRef(0)


def sell_one(left: int) -> fx.Effect[None]:
    if left == 0:
        return fx.void
    return stock.set(left - 1).and_then(sold.update(lambda n: n + 1))


def handle_requests() -> None:
    # Each call is a run of its own on this thread, as in a threaded web server.
    for _ in range(500):
        fx.run_blocking(requests.update(lambda n: n + 1))
        fx.run_blocking(fx.tx(stock.get().flat_map(sell_one)))


threads = [threading.Thread(target=handle_requests) for _ in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print("requests:", fx.run_blocking(requests.get()))
print("sold:", fx.run_blocking(sold.get()), "left:", fx.run_blocking(stock.get()))
