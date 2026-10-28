"""Single-step transactional reads and writes over ``TxRef`` values, the
building blocks of the transactional collections.

Each runs in the running transaction, or as a transaction of its own, in one
fiber step, so a read-then-write needs no ``tx`` wrapper to be atomic.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect
from pyfect.option import Option
from pyfect.transaction import Transaction, TransactionMeta, transactional, tx
from pyfect.tx_ref import TxRef


def read[A, B](ref: TxRef[A], f: Callable[[A], B]) -> Effect[B]:
    """``f`` of the ref's value in the transaction."""
    return transactional(lambda state: f(state._entry(ref)._value))


def read2[A, B, C](first: TxRef[A], second: TxRef[B], f: Callable[[A, B], C]) -> Effect[C]:
    """``f`` of two refs' values, read in one transaction."""
    return transactional(lambda state: f(state._entry(first)._value, state._entry(second)._value))


def update_reading[A, B](ref: TxRef[A], other: TxRef[B], f: Callable[[A, B], A]) -> Effect[None]:
    """Replace ``ref``'s value with ``f(value, other's value)``, both read
    in one transaction."""

    def run(state: TransactionMeta) -> None:
        source = state._entry(other)._value
        entry = state._entry(ref)
        entry._value = f(entry._value, source)
        entry._written = True

    return transactional(run)


def modify_or_skip[A, B](ref: TxRef[A], f: Callable[[A], tuple[B, Option[A]]]) -> Effect[B]:
    """Like ``TxRef.modify``, but ``f`` says whether to write: ``Some(value)``
    writes ``value`` (waking the ref's waiters even when it is the current
    value), ``None`` leaves the ref unwritten (Effect's ``remove`` /
    ``modify`` on a missing key)."""

    def run(state: TransactionMeta) -> B:
        entry = state._entry(ref)
        result, value = f(entry._value)
        if value is not None:
            entry._value = value.value
            entry._written = True
        return result

    return transactional(run)


def decide[A, E](f: Callable[[TransactionMeta], Effect[A, E, Transaction]]) -> Effect[A, E]:
    """``f``'s verdict, in the running transaction or one of its own. ``f``
    reads and writes refs with ``value`` and ``write`` in one step and
    returns the outcome: a success, a failure, or ``tx_retry``."""
    return tx(Transaction().flat_map(f))


def value[A](state: TransactionMeta, ref: TxRef[A]) -> A:
    """The ref's value in the transaction."""
    entry: Any = state._entry(ref)
    return entry._value


def write[A](state: TransactionMeta, ref: TxRef[A], new: A) -> None:
    """Write ``new`` to the ref in the transaction."""
    entry = state._entry(ref)
    entry._value = new
    entry._written = True
