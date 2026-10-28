from dataclasses import dataclass

import pyfect as fx


@dataclass
class InsufficientFunds(fx.TaggedError):
    account: str
    needed: int


@dataclass(frozen=True)
class Account:
    name: str
    balance: fx.TxRef[int]


def open_account(name: str, balance: int) -> Account:
    return Account(name, fx.TxRef(balance))


@fx.fn
def withdraw(account: Account, amount: int):
    balance = yield from account.balance.get()
    if balance < amount:
        return (yield from InsufficientFunds(account.name, amount - balance))
    yield from account.balance.set(balance - amount)


def deposit(account: Account, amount: int) -> fx.Effect[None]:
    return account.balance.update(lambda balance: balance + amount)


def transfer(source: Account, target: Account, amount: int) -> fx.Effect[None, InsufficientFunds]:
    # Both writes commit together or not at all: if the withdrawal fails, the
    # deposit made just before it is discarded.
    return fx.tx(deposit(target, amount).and_then(withdraw(source, amount)))


def total(*accounts: Account) -> fx.Effect[int]:
    return fx.tx(fx.for_each(accounts, lambda account: account.balance.get())).map(sum)


@fx.fn
def program():
    alice, bob = open_account("alice", 100), open_account("bob", 50)

    # A hundred transfers each way at once: whatever the interleaving, no money is
    # created or lost.
    moves = [transfer(alice, bob, 1) for _ in range(100)] + [
        transfer(bob, alice, 1) for _ in range(100)
    ]
    yield from fx.for_each(moves, lambda move: move.ignore(), concurrency="unbounded")
    assert (yield from total(alice, bob)) == 150

    # A failed transfer leaves both balances as they were.
    before = yield from alice.balance.get()
    failed = yield from transfer(bob, alice, 500).result()
    assert isinstance(failed, fx.Err) and failed.error.account == "bob"
    assert (yield from alice.balance.get()) == before
    assert (yield from total(alice, bob)) == 150


fx.run_sync(program())
