"""Effect core A: constructors, errors, Exit, Cause, Result, Option, and the
Filter / Predicate / Function modules they lean on."""

from api_coverage import Cluster, Module

ISINSTANCE = "`TypeId` symbols and `is*` guards"
ONE_NONE = "Option `none()` / `some(a)` / `isOption`"
AND_THEN = "`and_then(next)` takes the next Option / Result"
DO = "Do / bind / Option.gen"
ORDER = "Order, Equivalence, Combiner, Reducer"
PREDICATE = "Data.Class, TaggedEnum, Match, Predicate"
FUNCTION = "Function (pipe, flow, dual, …)"
FILTER = "Effect's `Filter` module"
EAGER = "`*Eager` variants"
SERVICE = "`Effect.service(tag)`, `Effect.scope`, `contextWith(f)`"
RUN_WITH = "`runForkWith(context)`"

EFFECT = Module(
    "Effect",
    "effect/src/Effect.ts",
    ("pyfect", "pyfect.effect", "pyfect:Effect"),
    renamed={
        "promise": "pyfect.from_async",
        "tryPromise": "pyfect.try_async",
        "fromNullishOr": "pyfect.from_optional",
        "catch": "pyfect.Effect.catch_all",
        "forkChild": "pyfect.Effect.fork",
        "forkDetach": "pyfect.Effect.fork_daemon",
        "fiber": "pyfect.current_fiber",
        "runPromise": "pyfect.run_async",
        "runPromiseExit": "pyfect.run_async_exit",
        "clockWith": "pyfect.clock.clock_with",
        "acquireDisposable": "pyfect.acquire_context",
    },
    pythonic={
        "TypeId": (ISINSTANCE, "`isinstance(x, Effect)`"),
        "isEffect": (ISINSTANCE, "`isinstance(x, Effect)`"),
        "whileLoop": ("`Effect.whileLoop`", "a `while` loop in `fx.gen`"),
        "undefined": (ONE_NONE, "`fx.void`"),
        "Do": (DO, "generator locals"),
        "bindTo": (DO, "generator locals"),
        "bind": (DO, "generator locals"),
        "let": (DO, "generator locals"),
        "yieldNowWith": ("`Effect.yieldNowWith(priority)`", "`yield_now()`"),
        "catchTags": ("`Effect.catchTags({ A: f, B: g })`", "chained `catch_tag`"),
        "contextWith": (SERVICE, "`fx.context(*tags).map(f)`"),
        "service": (SERVICE, "the tag: `Database()`"),
        "scope": (SERVICE, "the tag: `Scope()`"),
        "onExitPrimitive": ("`Effect.onExitPrimitive`", "`on_exit`"),
        "abortSignal": ("Effect.promise / tryPromise / callback(AbortSignal)", "`callback`"),
        "replicate": ("`Effect.replicate(n)`", "`[eff] * n`"),
        "spanAnnotations": ("`spanAnnotations`", "`tracer.TracerSpanAnnotations`"),
        "spanLinks": ("`spanAnnotations`", "`tracer.TracerSpanLinks`"),
        "tracer": ("`Effect.tracer`", "`tracer.CurrentTracer`"),
        "runForkWith": (RUN_WITH, "`run_fork(eff, context=)`"),
        "runCallbackWith": (RUN_WITH, "`run_callback(eff, context=)`"),
        "runPromiseWith": (RUN_WITH, "`run_async(eff, context=)`"),
        "runPromiseExitWith": (RUN_WITH, "`run_async_exit(eff, context=)`"),
        "runSyncWith": (RUN_WITH, "`run_sync(eff, context=)`"),
        "runSyncExitWith": (RUN_WITH, "`run_sync_exit(eff, context=)`"),
        "effectify": ("`Effect.effectify`", "`callback` / `from_async`"),
        "satisfiesSuccessType": ("`satisfiesSuccessType`", "an annotation"),
        "satisfiesErrorType": ("`satisfiesSuccessType`", "an annotation"),
        "satisfiesServicesType": ("`satisfiesSuccessType`", "an annotation"),
        "matchEager": (EAGER, "`match`"),
        "matchCauseEager": (EAGER, "`match_cause`"),
        "matchCauseEffectEager": (EAGER, "`match_cause_effect`"),
        "mapEager": (EAGER, "`map`"),
        "mapErrorEager": (EAGER, "`map_error`"),
        "mapBothEager": (EAGER, "`map_both`"),
        "flatMapEager": (EAGER, "`flat_map`"),
        "catchEager": (EAGER, "`catch_all`"),
        "fnUntracedEager": (EAGER, "`fn_untraced`"),
    },
)

EXIT = Module(
    "Exit",
    "effect/src/Exit.ts",
    ("pyfect.exit", "pyfect.exit:Success", "pyfect.exit:Failure"),
    pythonic={
        "isExit": (ISINSTANCE, "`isinstance(x, Success | Failure)`"),
        "findErrorOption": ("`findErrorOption`", "`find_error()`"),
    },
)

CAUSE = Module(
    "Cause",
    "effect/src/Cause.ts",
    ("pyfect.cause", "pyfect.cause:Cause", "pyfect.errors"),
    renamed={
        "combine": "pyfect.cause.Cause.__add__",
        "NoSuchElementError": "pyfect.errors.NoSuchElementException",
        "TimeoutError": "pyfect.errors.TimeoutException",
        "StackTrace": "pyfect.tracer.StackTrace",
        "InterruptorStackTrace": "pyfect.tracer.InterruptorStackTrace",
    },
    pythonic={
        "TypeId": (ISINSTANCE, "`isinstance(x, Cause)`"),
        "ReasonTypeId": (ISINSTANCE, "`isinstance(x, Reason)`"),
        **{
            name: ("Cause `isCause` / `is*Reason` / `make*Reason`", said)
            for name, said in {
                "isCause": "`isinstance(x, Cause)`",
                "isReason": "`isinstance(x, Reason)`",
                "isFailReason": "`isinstance(r, Fail)`",
                "isDieReason": "`isinstance(r, Die)`",
                "isInterruptReason": "`isinstance(r, Interrupt)`",
                "makeFailReason": "`Fail(error)`",
                "makeDieReason": "`Die(defect)`",
                "makeInterruptReason": "`Interrupt(fiber_id)`",
                "findErrorOption": "`find_error()`",
            }.items()
        },
        **{
            name: (ISINSTANCE, f"`isinstance(x, {cls})`")
            for name, cls in {
                "isNoSuchElementError": "NoSuchElementException",
                "NoSuchElementErrorTypeId": "NoSuchElementException",
                "isDone": "Done",
                "DoneTypeId": "Done",
                "TimeoutErrorTypeId": "TimeoutException",
                "isTimeoutError": "TimeoutException",
                "IllegalArgumentErrorTypeId": "IllegalArgumentError",
                "isIllegalArgumentError": "IllegalArgumentError",
                "isExceededCapacityError": "ExceededCapacityError",
                "ExceededCapacityErrorTypeId": "ExceededCapacityError",
                "AsyncFiberErrorTypeId": "AsyncioRequiredError",
                "isAsyncFiberError": "AsyncioRequiredError",
                "UnknownErrorTypeId": "UnknownError",
                "isUnknownError": "UnknownError",
            }.items()
        },
        "done": ("`Cause.done(value)`", "`fx.fail(Done(value))`"),
        "AsyncFiberError": (
            "`runSync` of an async effect throws `AsyncFiberError`",
            "`AsyncioRequiredError`",
        ),
    },
)

RESULT = Module(
    "Result",
    "effect/src/Result.ts",
    ("pyfect.result", "pyfect.result:Ok", "pyfect.result:Err"),
    renamed={
        "succeed": "pyfect.result.Ok",
        "fail": "pyfect.result.Err",
        "fromNullishOr": "pyfect.result.from_optional",
        "isFailure": "pyfect.result.is_err",
        "isSuccess": "pyfect.result.is_ok",
        "getSuccess": "pyfect.option.get_success",
        "getFailure": "pyfect.option.get_failure",
        "getOrNull": "pyfect.result.Ok.get_or_none",
        "getOrThrowWith": "pyfect.result.Ok.get_or_raise_with",
        "getOrThrow": "pyfect.result.Ok.get_or_raise",
    },
    pythonic={
        "makeEquivalence": (ORDER, "`==`"),
        "getOrUndefined": (ONE_NONE, "`get_or_none()`"),
        "andThen": (AND_THEN, "`and_then(next)`, `flat_map`, `map`"),
        "gen": (DO, "generator locals"),
        "Do": (DO, "generator locals"),
        "bind": (DO, "generator locals"),
        "bindTo": (DO, "generator locals"),
        "let": (DO, "generator locals"),
    },
)

OPTION = Module(
    "Option",
    "effect/src/Option.ts",
    ("pyfect.option",),
    renamed={
        "some": "pyfect.option.Some",
        "fromNullishOr": "pyfect.option.from_optional",
        "liftNullishOr": "pyfect.option.lift_optional",
        "flatMapNullishOr": "pyfect.option.flat_map_optional",
        "getOrNull": "pyfect.option.get_or_none",
        "getOrThrowWith": "pyfect.option.get_or_raise_with",
        "getOrThrow": "pyfect.option.get_or_raise",
        "toArray": "pyfect.option.to_list",
    },
    pythonic={
        "none": (ONE_NONE, "`None`"),
        "isOption": (ONE_NONE, "none: any value may be an absent Option"),
        "fromUndefinedOr": (ONE_NONE, "`from_optional`"),
        "fromNullOr": (ONE_NONE, "`from_optional`"),
        "getOrUndefined": (ONE_NONE, "`get_or_none`"),
        "andThen": (AND_THEN, "`and_then(o, next)`, `flat_map`, `as_`"),
        "makeEquivalence": (ORDER, "`==`"),
        "makeOrder": (ORDER, "`key=` functions"),
        "makeReducer": (ORDER, "`functools.reduce`"),
        "makeCombinerFailFast": (ORDER, "`option.all` / `functools.reduce`"),
        "makeReducerFailFast": (ORDER, "`option.all` / `functools.reduce`"),
        "bindTo": (DO, "generator locals"),
        "let": (DO, "generator locals"),
        "bind": (DO, "generator locals"),
        "Do": (DO, "generator locals"),
        "gen": (DO, "generator locals"),
    },
)

FILTER_MODULE = Module(
    "Filter",
    "effect/src/Filter.ts",
    ("pyfect.filters",),
    pythonic={
        "bigint": (FILTER, "`filters.instance_of(int)`"),
        "symbol": (FILTER, "none: Python has no symbols"),
        "tagged": (FILTER, "`filters.instance_of(cls)`"),
        "equalsStrict": (FILTER, "`filters.equals`"),
    },
)

PREDICATE_MODULE = Module(
    "Predicate",
    "effect/src/Predicate.ts",
    (),
    pythonic={
        name: (PREDICATE, said)
        for name, said in {
            "mapInput": "`lambda x: p(f(x))`",
            "isTupleOf": "`isinstance(x, tuple) and len(x) == n`",
            "isTupleOfAtLeast": "`isinstance(x, tuple) and len(x) >= n`",
            "isTruthy": "`bool`",
            "isSet": "`isinstance(x, set | frozenset)`",
            "isMap": "`isinstance(x, Mapping)`",
            "isString": "`isinstance(x, str)`",
            "isNumber": "`isinstance(x, int | float)`",
            "isBoolean": "`isinstance(x, bool)`",
            "isBigInt": "`isinstance(x, int)`",
            "isSymbol": "none: Python has no symbols",
            "isPropertyKey": "`isinstance(x, str)`",
            "isFunction": "`callable`",
            "isUndefined": "`x is None`",
            "isNotUndefined": "`x is not None`",
            "isNull": "`x is None`",
            "isNotNull": "`x is not None`",
            "isNullish": "`x is None`",
            "isNotNullish": "`x is not None`",
            "isNever": "`typing.assert_never`",
            "isUnknown": "`lambda _: True`",
            "isObjectOrArray": "`isinstance(x, object)`",
            "isObject": "`isinstance(x, object)`",
            "isReadonlyObject": "`isinstance(x, object)`",
            "isObjectKeyword": "`isinstance(x, object)`",
            "hasProperty": "`hasattr`",
            "isTagged": "`isinstance(x, cls)`",
            "isError": "`isinstance(x, BaseException)`",
            "isUint8Array": "`isinstance(x, bytes)`",
            "isDate": "`isinstance(x, datetime)`",
            "isIterable": "`isinstance(x, Iterable)`",
            "isPromise": "`inspect.isawaitable`",
            "isPromiseLike": "`inspect.isawaitable`",
            "isRegExp": "`isinstance(x, re.Pattern)`",
            "compose": "`lambda a: p(a) and q(a)` with `TypeIs`",
            "Tuple": "`all(p(x) for p, x in zip(ps, xs))`",
            "Struct": "`all(p(getattr(x, k)) for k, p in ps.items())`",
            "not": "`not p(x)`",
            "or": "`p(x) or q(x)`",
            "and": "`p(x) and q(x)`",
            "xor": "`p(x) != q(x)`",
            "eqv": "`p(x) == q(x)`",
            "implies": "`not p(x) or q(x)`",
            "nor": "`not (p(x) or q(x))`",
            "nand": "`not (p(x) and q(x))`",
            "every": "`all(p(x) for p in ps)`",
            "some": "`any(p(x) for p in ps)`",
        }.items()
    },
)

FUNCTION_MODULE = Module(
    "Function",
    "effect/src/Function.ts",
    (),
    pythonic={
        name: (FUNCTION, said)
        for name, said in {
            "dual": "methods plus curried functions",
            "apply": "`f(a)`",
            "identity": "`lambda a: a`",
            "satisfies": "an annotation",
            "cast": "`typing.cast`",
            "constant": "`lambda: a`",
            "constTrue": "`lambda: True`",
            "constFalse": "`lambda: False`",
            "constNull": "`lambda: None`",
            "constUndefined": "`lambda: None`",
            "constVoid": "`lambda: None`",
            "flip": "`lambda b, a: f(a, b)`",
            "compose": "`lambda a: g(f(a))`",
            "absurd": "`typing.assert_never`",
            "tupled": "`lambda t: f(*t)`",
            "untupled": "`lambda *a: f(a)`",
            "pipe": "single-step `.pipe`",
            "flow": "`lambda a: g(f(a))`",
            "hole": "none: a type-level placeholder",
            "SK": "`lambda _, b: b`",
            "memoize": "`functools.cache`",
            "memoizeIdempotent": "`functools.cache`",
        }.items()
    },
)

CLUSTER = Cluster(
    name="core-a",
    title="Effect core A (Effect, Exit, Cause, Result, Option, Filter, Predicate, Function)",
    modules=(EFFECT, EXIT, CAUSE, RESULT, OPTION, FILTER_MODULE, PREDICATE_MODULE, FUNCTION_MODULE),
)
