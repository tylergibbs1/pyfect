// Effect 4.1.2's side of the runtime differential tester (tests/runtime_diff):
//   node tests/runtime_diff/effect_interpreter.ts PROGRAMS.json > ANSWERS.json
//   node tests/runtime_diff/effect_interpreter.ts --serve   (a program per stdin line, an answer per line)
// PROGRAMS.json is a list of programs in program.py's JSON form; each answer is
// {"exit": ..., "log": [...], "stuck": bool}, what interpret.py computes in pyfect.
// Reads Effect's sources from $PYFECT_EFFECT_REF (an Effect 4.1.2 checkout). Node 24 runs
// TypeScript. Keep it in step with interpret.py: the two must build the same program.
import { readFileSync } from "node:fs"
import { registerHooks } from "node:module"
import { createInterface } from "node:readline"

const R = `${process.env.PYFECT_EFFECT_REF}/packages/effect/src/`

// One Effect bug pyfect does not copy (docs/PARITY.md §4, §5 item 14), fixed here
// so the comparison sees past it: a fiber ending while interrupted, with a child
// that does not end at once when interrupted, waits for it interruptibly, so the
// wait is cut short and the fiber's exit is replaced by the bare interruption (a
// finalizer's defect is lost). pyfect waits for its children uninterruptibly.
const EXIT_WAIT = "return this.evaluate(flatMap(interruptChildren, () => exit) as any)"
registerHooks({
  load(url, context, nextLoad) {
    const loaded = nextLoad(url, context)
    if (!url.endsWith("/packages/effect/src/internal/effect.ts")) return loaded
    const source = String(loaded.source)
    if (!source.includes(EXIT_WAIT)) throw new Error("internal/effect.ts changed: update EXIT_WAIT")
    return {
      ...loaded,
      source: source.replace(EXIT_WAIT, `this.interruptible = false; ${EXIT_WAIT}`)
    }
  }
})
const Effect: any = await import(R + "Effect.ts")
const Exit: any = await import(R + "Exit.ts")
const Fiber: any = await import(R + "Fiber.ts")
const Clock: any = await import(R + "Clock.ts")
const Queue: any = await import(R + "Queue.ts")
const Deferred: any = await import(R + "Deferred.ts")
const Semaphore: any = await import(R + "Semaphore.ts")
const Schedule: any = await import(R + "Schedule.ts")
const Stream: any = await import(R + "Stream.ts")
const References: any = await import(R + "References.ts")
const TestClock: any = await import(R + "testing/TestClock.ts")

type Json = null | boolean | number | string | Array<Json> | { [key: string]: Json }
type Node = { op: string; [field: string]: any }

const Option: any = await import(R + "Option.ts")
const Result: any = await import(R + "Result.ts")

// A program value as JSON: Options as {"some": v} / "none", Results as
// {"success": v} / {"failure": e}.
const json = (value: any): Json => {
  if (value === undefined || value === null) return null
  if (Array.isArray(value)) return value.map(json)
  if (Option.isOption(value)) return Option.isSome(value) ? { some: json(value.value) } : "none"
  if (Result.isResult(value)) {
    return Result.isSuccess(value) ? { success: json(value.success) } : { failure: errorName(value.failure) }
  }
  if (typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, json(v)]))
  return value
}
const errorName = (error: any): Json =>
  typeof error === "string"
    ? error
    : error !== null && typeof error === "object" && "_tag" in error
    ? `tag:${error._tag}`
    : `other:${String(error)}`
const cause = (c: any): Json =>
  c.reasons.map((r: any) =>
    r._tag === "Fail" ? ["fail", errorName(r.error)] : r._tag === "Die" ? ["die", errorName(r.defect)] : ["interrupt"]
  )
const exit = (e: any): Json => (Exit.isSuccess(e) ? { ok: json(e.value) } : { cause: cause(e.cause) })
const millis = (ms: number) => `${ms} millis`
const range = (n: number) => Array.from({ length: n }, (_, i) => i)
const concurrency = (c: Json) => (c === null ? {} : { concurrency: c })

function runProgram(program: Node) {
  const log: Array<Json> = []
  const attempts = new Map<string, number>()

  const event = (ctx: string, id: number, name: string, detail: unknown = null) =>
    Effect.flatMap(Clock.currentTimeMillis, (now: number) =>
      Effect.sync(() => {
        log.push([now, ctx, id, name, json(detail)])
      })
    )

  const schedule = (s: Node) => {
    switch (s.op) {
      case "Recurs":
        return { policy: Schedule.recurs(s.times) }
      case "Spaced":
        return { options: { schedule: Schedule.spaced(millis(s.ms)), times: s.times } }
      case "Exponential":
        return { options: { schedule: Schedule.exponential(millis(s.ms)), times: s.times } }
    }
    throw new Error(`schedule ${s.op}`)
  }

  const source = (s: Node, ctx: string): any => {
    switch (s.op) {
      case "Items": {
        const items = Stream.fromIterable(s.values)
        return s.chunk === null ? items : Stream.rechunk(items, s.chunk)
      }
      case "FailAfter":
        return Stream.concat(Stream.fromIterable(s.values), Stream.fail(`e${s.id}`))
      case "FromEffect":
        return Stream.fromEffect(Effect.as(run(s.body, ctx), s.id))
    }
    throw new Error(`source ${s.op}`)
  }

  const streamOp = (stream: any, o: Node, ctx: string): any => {
    switch (o.op) {
      case "MapAdd":
        return Stream.map(stream, (x: number) => x + o.add)
      case "FilterOdd":
        return Stream.filter(stream, (x: number) => x % 2 === 1)
      case "Take":
        return Stream.take(stream, o.n)
      case "TakeWhileBelow":
        return Stream.takeWhile(stream, (x: number) => x < o.limit)
      case "Drop":
        return Stream.drop(stream, o.n)
      case "Tap":
        return Stream.tap(stream, (x: number) => event(ctx, o.id, "element", x))
      case "MapEffect":
        return Stream.mapEffect(
          stream,
          (x: number) => Effect.as(run(o.body, `${ctx}${o.id}.${x}/`), x),
          concurrency(o.concurrency)
        )
      case "ScanSum":
        return Stream.scan(stream, () => 0, (a: number, x: number) => a + x)
      case "GroupedSum":
        return Stream.map(Stream.grouped(stream, o.n), (g: Array<number>) => g.reduce((a, x) => a + x, 0))
      case "CatchStream":
        return Stream.catch(stream, (e: unknown) =>
          Stream.unwrap(Effect.as(event(ctx, o.id, "caught", errorName(e)), source(o.source, ctx)))
        )
      case "Merge":
        return Stream.merge(stream, source(o.source, ctx))
      case "Concat":
        return Stream.concat(stream, source(o.source, ctx))
      case "Buffer":
        return Stream.buffer(stream, { capacity: o.capacity })
      case "ZipSum":
        return Stream.map(Stream.zip(stream, source(o.source, ctx)), ([a, b]: [number, number]) => a + b)
      case "FlatMapStream":
        return Stream.flatMap(
          stream,
          (x: number) => Stream.map(source(o.source, `${ctx}${o.id}.${x}/`), (y: number) => y + x),
          concurrency(o.concurrency)
        )
      case "ScheduleSpaced":
        return Stream.schedule(stream, Schedule.spaced(millis(o.ms)))
    }
    throw new Error(`stream op ${o.op}`)
  }

  const sink = (stream: any, kind: string): any => {
    switch (kind) {
      case "collect":
        return Stream.runCollect(stream)
      case "sum":
        return Stream.runFold(stream, () => 0, (a: number, x: number) => a + x)
      case "drain":
        return Stream.runDrain(stream)
      case "count":
        return Stream.runCount(stream)
    }
    throw new Error(`sink ${kind}`)
  }

  const finalizer = (e: Node, ctx: string): any => Effect.orDie(run(e, ctx))

  const run = (e: Node, ctx: string): any => {
    const at = (name: string, detail: unknown = null) => event(ctx, e.id, name, detail)
    switch (e.op) {
      case "Succeed":
        return Effect.succeed(e.value)
      case "Fail":
        return Effect.fail(`e${e.id}`)
      case "Die":
        return Effect.die(`d${e.id}`)
      case "Interrupt":
        return Effect.interrupt
      case "Log":
        return Effect.as(at("log"), e.id)
      case "Sleep":
        return Effect.as(Effect.andThen(Effect.sleep(millis(e.ms)), at("woke")), e.ms)
      case "YieldNow":
        return Effect.as(Effect.andThen(Effect.yieldNow, at("resumed")), null)
      case "Flaky":
        return Effect.suspend(() => {
          const key = `${ctx}${e.id}`
          const attempt = (attempts.get(key) ?? 0) + 1
          attempts.set(key, attempt)
          return Effect.andThen(
            at("attempt", attempt),
            attempt <= e.failures ? Effect.fail(`e${e.id}`) : Effect.succeed(attempt)
          )
        })
      case "Seq":
        return e.items.reduce((acc: any, item: Node) => Effect.andThen(acc, run(item, ctx)), Effect.succeed(null))
      case "FlatMap":
        return Effect.flatMap(run(e.first, ctx), (v: Json) => Effect.andThen(at("value", v), run(e.then, ctx)))
      case "Catch":
        return Effect.catch(run(e.body, ctx), (err: unknown) => Effect.andThen(at("caught", errorName(err)), run(e.handler, ctx)))
      case "CatchCause":
        return Effect.catchCause(run(e.body, ctx), (c: unknown) => Effect.andThen(at("cause", cause(c)), run(e.handler, ctx)))
      case "CatchDefect":
        return Effect.catchDefect(run(e.body, ctx), (d: unknown) => Effect.andThen(at("defect", errorName(d)), run(e.handler, ctx)))
      case "Fork":
        return Effect.gen(function*() {
          const fork = e.daemon ? Effect.forkDetach : Effect.forkChild
          const fiber = yield* fork(run(e.child, ctx), {
            startImmediately: e.start_immediately,
            uninterruptible: e.uninterruptible
          })
          const body = yield* run(e.body, ctx)
          switch (e.end) {
            case "join":
              return [body, yield* Fiber.join(fiber)]
            case "interrupt":
              yield* Fiber.interrupt(fiber)
              yield* at("interrupted")
              return [body, null]
            case "await":
              return [body, exit(yield* Fiber.await(fiber))]
            default:
              return [body, null]
          }
        })
      case "Race":
        return (e.first ? Effect.raceFirst : Effect.race)(run(e.left, ctx), run(e.right, ctx))
      case "RaceAll":
        return Effect.raceAll(e.items.map((item: Node) => run(item, ctx)))
      case "Timeout":
        return Effect.timeout(run(e.body, ctx), millis(e.ms))
      case "Scoped":
        return Effect.scoped(Effect.gen(function*() {
          for (const [i, resource] of e.resources.entries()) {
            yield* Effect.acquireRelease(
              run(resource.acquire, ctx),
              (_: unknown, x: unknown) => Effect.andThen(at("release", [i, exit(x)]), finalizer(resource.release, ctx))
            )
          }
          return yield* run(e.body, ctx)
        }))
      case "AcquireUseRelease":
        return Effect.acquireUseRelease(
          run(e.acquire, ctx),
          () => run(e.use, ctx),
          (_: unknown, x: unknown) => Effect.andThen(at("release", exit(x)), run(e.release, ctx))
        )
      case "Ensuring":
        return Effect.ensuring(run(e.body, ctx), Effect.andThen(at("ensuring"), finalizer(e.finalizer, ctx)))
      case "OnExit":
        return Effect.onExit(run(e.body, ctx), (x: unknown) => Effect.andThen(at("exit", exit(x)), finalizer(e.finalizer, ctx)))
      case "OnInterrupt":
        return Effect.onInterrupt(run(e.body, ctx), () => Effect.andThen(at("interrupted"), finalizer(e.finalizer, ctx)))
      case "Interruptible":
        return Effect.interruptible(run(e.body, ctx))
      case "All":
        return Effect.all(e.items.map((item: Node) => run(item, ctx)), { ...concurrency(e.concurrency), mode: e.mode })
      case "TimeoutOption":
        return Effect.timeoutOption(run(e.body, ctx), millis(e.ms))
      case "Exited":
        return Effect.flatMap(Effect.exit(run(e.body, ctx)), (x: unknown) => {
          const found = exit(x)
          return Effect.as(at("exited", found), found)
        })
      case "Uninterruptible":
        return Effect.uninterruptible(run(e.body, ctx))
      case "ForEach":
        return Effect.forEach(range(e.count), (i: number) => run(e.body, `${ctx}${e.id}.${i}/`), concurrency(e.concurrency))
      case "Retry": {
        const s = schedule(e.schedule)
        return Effect.retry(run(e.body, ctx), s.policy ?? s.options)
      }
      case "Repeat": {
        const s = schedule(e.schedule)
        return Effect.repeat(run(e.body, ctx), s.policy ?? s.options)
      }
      case "QueueHandoff":
        return Effect.gen(function*() {
          const queue = yield* Queue.bounded(e.capacity)
          const producer = yield* Effect.forkChild(
            Effect.forEach(range(e.items), (i: number) =>
              Effect.andThen(Queue.offer(queue, i), at("offered", i)), { discard: true })
          )
          const taken = yield* Effect.forEach(range(e.takes), () =>
            Effect.tap(Queue.take(queue), (v: number) => at("took", v)))
          yield* Fiber.interrupt(producer)
          yield* at("producer", exit(yield* Fiber.await(producer)))
          return taken
        })
      case "DeferredHandoff":
        return Effect.gen(function*() {
          const deferred = yield* Deferred.make()
          const waiters = yield* Effect.forEach(range(e.waiters), (i: number) =>
            Effect.forkChild(Effect.onExit(Deferred.await(deferred), (x: unknown) => at("woke", [i, exit(x)]))))
          const done = yield* Effect.exit(run(e.complete, ctx))
          yield* Deferred.done(deferred, done)
          return yield* Effect.forEach(waiters, (fiber: any) => Effect.map(Fiber.await(fiber), exit))
        })
      case "SemaphoreGate":
        return Effect.gen(function*() {
          const semaphore = yield* Semaphore.make(e.permits)
          return yield* Effect.forEach(range(e.count), (i: number) =>
            Semaphore.withPermits(semaphore, 1)(
              Effect.andThen(event(`${ctx}${e.id}.${i}/`, e.id, "permit"), run(e.body, `${ctx}${e.id}.${i}/`))
            ), { concurrency: "unbounded" })
        })
      case "StreamRun": {
        let stream = source(e.source, ctx)
        for (const o of e.ops) stream = streamOp(stream, o, ctx)
        return sink(stream, e.sink)
      }
    }
    throw new Error(`expr ${e.op}`)
  }

  const main = Effect.gen(function*() {
    // Started by clock wakes, so the test clock's adjust waits for all of their work.
    const fiber = yield* Effect.forkDetach(Effect.andThen(Effect.sleep(millis(1)), run(program, "")))
    yield* TestClock.adjust("1 hour")
    const stuck = fiber.pollUnsafe() === undefined
    if (stuck) {
      yield* Effect.forkDetach(Effect.andThen(Effect.sleep(millis(1)), Fiber.interrupt(fiber)))
      yield* TestClock.adjust("1 hour")
    }
    const done = fiber.pollUnsafe()
    // An uninterruptible program can wait forever: its exit is null.
    return { exit: done === undefined ? null : exit(done), log, stuck }
  })
  return main.pipe(
    Effect.provideService(References.MaxOpsBeforeYield, Number.MAX_SAFE_INTEGER),
    Effect.provide(TestClock.layer()),
    Effect.runPromise
  )
}

const answer = async (program: Node): Promise<Json> => {
  try {
    return await runProgram(program)
  } catch (error) {
    return { crashed: String(error) }
  }
}

if (process.argv[2] === "--serve") {
  // One program per line in, one answer per line out, for as long as stdin is open.
  for await (const line of createInterface({ input: process.stdin })) {
    process.stdout.write(JSON.stringify(await answer(JSON.parse(line))) + "\n")
  }
} else {
  const programs: Array<Node> = JSON.parse(readFileSync(process.argv[2], "utf8"))
  const answers: Array<Json> = []
  for (const program of programs) answers.push(await answer(program))
  console.log(JSON.stringify(answers))
}
