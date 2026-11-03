"""An ``AsyncioScheduler`` whose loop is about to close hands its work to a successor
(``hand_off``); a task handed to it once its loop has closed with no successor is a
``LoopClosedError`` where it was handed over, never a silent loss (dogfood quill #1)."""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading
import time

import pytest

import pyfect as fx
from pyfect import scheduler
from pyfect.duration import Seconds
from pyfect.scheduler import AsyncioScheduler, LoopClosedError, SyncScheduler


def _on_loop_thread() -> tuple[asyncio.AbstractEventLoop, AsyncioScheduler, threading.Thread]:
    loop = asyncio.new_event_loop()
    made: list[AsyncioScheduler] = []
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        made.append(AsyncioScheduler(loop))
        ready.set()
        loop.run_forever()
        loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(5)
    return loop, made[0], thread


def _hand_off_and_stop(
    loop: asyncio.AbstractEventLoop, sched: AsyncioScheduler, successor: SyncScheduler
) -> None:
    def go() -> None:
        sched.hand_off(successor)
        loop.call_soon(loop.stop)

    loop.call_soon_threadsafe(go)


def test_after_a_hand_off_tasks_and_timers_run_on_the_successor() -> None:
    loop, sched, thread = _on_loop_thread()
    successor = SyncScheduler()
    ran: list[str] = []
    timer_ran = threading.Event()

    def arm() -> None:
        def fire() -> None:
            ran.append("timer")
            timer_ran.set()

        sched.call_later(Seconds(0.05), fire)
        sched.call_later(Seconds(0.05), lambda: ran.append("cancelled"))()

    loop.call_soon_threadsafe(lambda: sched.schedule(arm))
    _hand_off_and_stop(loop, sched, successor)
    thread.join(5)
    assert loop.is_closed()

    sched.schedule(lambda: ran.append("later"))
    successor.run_until(timer_ran.is_set)
    assert sorted(ran) == ["later", "timer"]


def test_a_task_handed_over_from_another_thread_during_the_hand_off_is_not_lost() -> None:
    loop, sched, thread = _on_loop_thread()
    successor = SyncScheduler()
    ran: list[int] = []
    stop = threading.Event()

    def flood() -> None:
        i = 0
        while not stop.is_set():
            sched.schedule(lambda n=i: ran.append(n))
            i += 1
            time.sleep(0)
        ran.append(-i)  # how many were sent

    sender = threading.Thread(target=flood)
    sender.start()
    time.sleep(0.01)
    _hand_off_and_stop(loop, sched, successor)
    thread.join(5)
    stop.set()
    sender.join(5)
    sent = -min(ran)
    successor.run_until(lambda: len(ran) == sent + 1)
    assert sorted(n for n in ran if n >= 0) == list(range(sent))


def test_a_task_for_a_closed_loop_with_no_successor_is_a_loop_closed_error() -> None:
    loop, sched, thread = _on_loop_thread()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    with pytest.raises(LoopClosedError):
        sched.schedule(lambda: None)


def test_interrupting_a_fiber_whose_loop_closed_is_a_defect_of_the_interrupter() -> None:
    loop, sched, thread = _on_loop_thread()
    started = threading.Event()
    fibers: list[fx.Fiber[object, object]] = []

    def fork() -> None:
        fibers.append(fx.run_fork(fx.never, scheduler=sched))
        started.set()

    loop.call_soon_threadsafe(fork)
    started.wait(5)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    exit = fx.run_sync_exit(fibers[0].interrupt())
    assert isinstance(exit, fx.Failure)
    assert isinstance(exit.cause.squash(), LoopClosedError)


def test_the_scheduler_hands_tasks_to_a_loop_only_through_the_closed_loop_guard() -> None:
    # Every cross-thread hand-off onto the loop goes through _call_soon_threadsafe,
    # which turns a closed loop into a LoopClosedError.
    tree = ast.parse(inspect.getsource(scheduler))
    callers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for call in ast.walk(node)
        if isinstance(call, ast.Attribute) and call.attr == "call_soon_threadsafe"
    }
    assert callers == {"_call_soon_threadsafe"}
