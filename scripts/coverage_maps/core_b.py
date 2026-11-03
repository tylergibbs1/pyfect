"""Effect core B: concurrency, resources and runtime entry. ``Effect.ts``
itself is in core A (every export); this cluster covers the modules around
it: Scope, Layer, Context, ManagedRuntime, Fiber, References, Scheduler,
Semaphore, Latch and Runtime."""

from api_coverage import Cluster, Module

ISINSTANCE = "`TypeId` symbols and `is*` guards"
MEMO_MAP = "`Layer.makeMemoMap` / `forkMemoMap` / `makeMemoMapUnsafe`"
SATISFIES = "`satisfiesSuccessType`"
KEYS = "Context keys"
YIELD_HOOK = "`Scheduler.shouldYield(fiber)` and `makeDispatcher`"
REPORTED = "`Runtime.errorReported`"

SCOPE = Module(
    "Scope",
    "effect/src/Scope.ts",
    ("pyfect.scope", "pyfect.scope:CloseableScope"),
    renamed={
        "makeUnsafe": "pyfect.scope.CloseableScope",
        "addFinalizerExit": "pyfect.scope.CloseableScope.add_finalizer",
    },
    pythonic={
        "addFinalizer": (
            "`Scope.addFinalizer(scope, effect)`",
            "`scope.add_finalizer(lambda _: effect)`",
        ),
    },
)

LAYER = Module(
    "Layer",
    "effect/src/Layer.ts",
    ("pyfect.layer", "pyfect.layer:Layer"),
    renamed={
        "mergeAll": "pyfect.layer.merge",
        "catch": "pyfect.layer.Layer.catch_all",
    },
    pythonic={
        "isLayer": (ISINSTANCE, "`isinstance(x, Layer)`"),
        "makeMemoMapUnsafe": (MEMO_MAP, "`layer.MemoMap()`"),
        "makeMemoMap": (MEMO_MAP, "`layer.MemoMap()`"),
        "forkMemoMapUnsafe": (MEMO_MAP, "`memo_map.fork()`"),
        "forkMemoMap": (MEMO_MAP, "`memo_map.fork()`"),
        "satisfiesSuccessType": (SATISFIES, "an annotation"),
        "satisfiesErrorType": (SATISFIES, "an annotation"),
        "satisfiesServicesType": (SATISFIES, "an annotation"),
    },
)

CONTEXT = Module(
    "Context",
    "effect/src/Context.ts",
    ("pyfect.context", "pyfect.context:Context"),
    renamed={
        "Service": "pyfect.context.Tag",
        "getOrUndefined": "pyfect.context.Context.get_or_none",
    },
    pythonic={
        "ServiceTypeId": (ISINSTANCE, "`issubclass(tag, Tag)`"),
        "isContext": (ISINSTANCE, "`isinstance(x, Context)`"),
        "isKey": (ISINSTANCE, "`issubclass(tag, Tag)`"),
        "isReference": (ISINSTANCE, "`issubclass(tag, Reference)`"),
        "makeUnsafe": (
            "`Context.mapUnsafe` keyed by key string; `makeUnsafe(map)` keeps the map",
            "`Context(mapping)`",
        ),
        "addUnsafe": (KEYS, "`ctx.add(tag, service)`"),
        "getOrUndefinedUnsafe": (KEYS, "`ctx.get_or_none(tag)`"),
        "hasSameCache": ("`Context.hasSameCache`", "not ported"),
    },
)

MANAGED_RUNTIME = Module(
    "ManagedRuntime",
    "effect/src/ManagedRuntime.ts",
    ("pyfect.managed_runtime", "pyfect.managed_runtime:ManagedRuntime"),
    pythonic={"isManagedRuntime": (ISINSTANCE, "`isinstance(x, ManagedRuntime)`")},
)

FIBER = Module(
    "Fiber",
    "effect/src/Fiber.ts",
    ("pyfect._fiber:Fiber",),
    renamed={"await": "pyfect.Fiber.await_exit"},
    pythonic={"isFiber": (ISINSTANCE, "`isinstance(x, Fiber)`")},
)

REFERENCES = Module(
    "References",
    "effect/src/References.ts",
    ("pyfect.logger", "pyfect.tracer", "pyfect.scheduler"),
    renamed={
        "Tracer": "pyfect.tracer.CurrentTracer",
        "Scheduler": "pyfect.scheduler.CurrentScheduler",
    },
)

SCHEDULER = Module(
    "Scheduler",
    "effect/src/Scheduler.ts",
    ("pyfect.scheduler",),
    renamed={"Scheduler": "pyfect.scheduler.CurrentScheduler"},
    pythonic={"MixedScheduler": (YIELD_HOOK, "`SyncScheduler` / `AsyncioScheduler`")},
)

SEMAPHORE = Module(
    "Semaphore",
    "effect/src/Semaphore.ts",
    ("pyfect.semaphore", "pyfect.semaphore:Semaphore"),
    renamed={
        "makeUnsafe": "pyfect.semaphore.Semaphore",
        "withPermit": "pyfect.semaphore.Semaphore.with_permits",
    },
)

LATCH = Module(
    "Latch",
    "effect/src/Latch.ts",
    ("pyfect.latch", "pyfect.latch:Latch"),
    renamed={"makeUnsafe": "pyfect.latch.Latch", "await": "pyfect.latch.Latch.wait"},
)

RUNTIME = Module(
    "Runtime",
    "effect/src/Runtime.ts",
    ("pyfect.run",),
    pythonic={
        "makeRunMain": ("`Runtime.makeRunMain(f)`", "`run_main`"),
        "errorExitCode": (REPORTED, "an `exit_code` attribute"),
        "errorReported": (REPORTED, "an `error_reported` attribute"),
    },
)

CLUSTER = Cluster(
    "core-b",
    "Effect core B (Scope, Layer, Context, ManagedRuntime, Fiber, References, Scheduler,"
    " Semaphore, Latch, Runtime)",
    (
        SCOPE,
        LAYER,
        CONTEXT,
        MANAGED_RUNTIME,
        FIBER,
        REFERENCES,
        SCHEDULER,
        SEMAPHORE,
        LATCH,
        RUNTIME,
    ),
)
