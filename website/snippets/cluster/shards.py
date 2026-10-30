from collections import Counter

import pyfect as fx
from pyfect.cluster import MachineId, runner_address, sharding_config, snowflake
from pyfect.hash_ring import HashRing

shards = sharding_config.DEFAULTS.shards_per_group
print("shards per group:", shards)

# Shards are spread over runners by consistent hashing, weighted per runner.
ring = HashRing[runner_address.RunnerAddress]()
a, b, c = (runner_address.make(f"runner-{n}", 34431) for n in "abc")
ring.add_many([a, b])
ring.add(c, weight=2)


def assign() -> list[runner_address.RunnerAddress]:
    return ring.get_shards(shards) or []  # None when the ring is empty


before = assign()
print(sorted(Counter(r.host for r in before).items()))

# When a runner leaves, its shards are spread over the others, weight kept.
ring.remove(b)
after = assign()
print(sorted(Counter(r.host for r in after).items()))
print("moved:", sum(x != y for x, y in zip(before, after, strict=True)))


# Snowflakes: ids ordered by time, unique per machine, for messages and requests.
@fx.fn
def ids():
    generator = yield from snowflake.Generator()
    yield from generator.set_machine_id(MachineId(7))
    first, second = generator.unsafe_next(), generator.unsafe_next()
    print(first < second, snowflake.machine_id(first), snowflake.sequence(second))


fx.run_main(ids().pipe(fx.provide(snowflake.layer_generator)))
