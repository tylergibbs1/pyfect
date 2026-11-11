from dataclasses import dataclass
from typing import Never

import pyfect as fx
from pyfect import layer


class Database(fx.Tag[str]): ...


class Ledger(fx.Tag[str]):
    """Built over the tenant's Database."""


@dataclass
class UnknownTenant(fx.TaggedError):
    tenant: str


DATABASES = {"acme": "acme.db", "globex": "globex.db"}


def database(tenant: str) -> fx.Layer[Database, UnknownTenant]:
    if tenant not in DATABASES:
        return layer.effect(Database, fx.fail(UnknownTenant(tenant)))
    return layer.succeed(Database, DATABASES[tenant])


def make_ledger() -> fx.Layer[Ledger, Never, Database]:
    return layer.effect(Ledger, Database().map(lambda db: f"ledger on {db}"))


# Unsafe: one layer object, so every tenant built while it is held gets the first build.
ledger_constant = make_ledger()


def unsafe_lookup(tenant: str) -> fx.Layer[Database | Ledger, UnknownTenant]:
    return ledger_constant.pipe(layer.provide_merge(database(tenant)))


# Safe: the lookup makes a new layer for each key.
def lookup(tenant: str) -> fx.Layer[Database | Ledger, UnknownTenant]:
    return make_ledger().pipe(layer.provide_merge(database(tenant)))


# The third type parameter is what a lookup can fail with.
class Tenants(fx.LayerMapService[str, Database | Ledger, UnknownTenant]): ...


def ledger_of(tenant: str) -> fx.Effect[str, Never, Tenants]:
    found = Ledger().pipe(fx.provide(Tenants.get(tenant)))
    return found.pipe(fx.catch_tag(UnknownTenant, lambda e: fx.succeed(f"no {e.tenant}")))


program = fx.all(ledger_of("acme"), ledger_of("globex"), ledger_of("initech"))

for name, tenant_layer in [("unsafe", unsafe_lookup), ("per key", lookup)]:
    tenants = Tenants.layer(tenant_layer, idle_time_to_live="1 minute")
    print(f"{name}:", fx.run_blocking(program.pipe(fx.provide(tenants))))
