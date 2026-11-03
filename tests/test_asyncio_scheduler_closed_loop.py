"""A task handed to an ``AsyncioScheduler`` once its loop has closed is a ``LoopClosedError``
where it was handed over, never a silent loss or a hang (dogfood quill #1: fibers a request
left on uvicorn's stopped loop were interrupted into nothing)."""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading

import pytest

import pyfect as fx
from pyfect import scheduler
from pyfect.scheduler import AsyncioScheduler, LoopClosedError


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


def test_a_task_for_a_closed_loop_is_a_loop_closed_error() -> None:
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
