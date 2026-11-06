import pyfect as fx

fetched: list[str] = []


def fetch_country(code: str) -> fx.Effect[str]:
    return fx.sync(lambda: fetched.append(code)).as_(f"country {code}")


@fx.gen
def program():
    # One lookup per key, shared by every caller; at most 100 entries, each for 60 s.
    countries = yield from fx.Cache.make(fetch_country, capacity=100, time_to_live=60)
    first = yield from fx.all(
        countries.get("PT"), countries.get("PT"), countries.get("ES"), concurrency="unbounded"
    )
    again = yield from countries.get("PT")
    return first, again


first, again = fx.run_blocking(program)
assert first == ("country PT", "country PT", "country ES")
assert again == "country PT"
assert fetched == ["PT", "ES"]
