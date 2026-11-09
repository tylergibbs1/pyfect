# Changelog

## 0.2.1 (unreleased)

### Breaking

- URLs are `fx.Url` (also `pyfect.http.url.Url`), JavaScript's `URL` as an immutable Python
  value, parsed by a full port of the WHATWG URL Standard that gives Node's results on the
  web-platform-tests URL suite (international domain names through UTS #46, `URL`'s setters,
  `URLSearchParams`). It was a `urllib.parse.SplitResult` subclass: use `url.protocol`,
  `url.host` / `url.hostname`, `url.port` (a string, `""` when absent), `url.pathname`,
  `url.search`, `url.hash` and `url.search_params` instead of `scheme`, `netloc`, `path`,
  `query`, `fragment` and `_replace`. `Url(text, base)` parses (raising `ValueError`),
  `Url.parse` gives `None` for text that isn't a URL and `Url.can_parse` asks. Two URLs are
  equal when their `href` is. The `http.url` setters take a `Url`, not any `SplitResult`;
  `http.url.mutate` is new.
- `config.url` and the `URL` / `URLFromString` schemas normalize as `new URL` does:
  `https://example.com` is `https://example.com/`, so `f"{url}payouts"` (not `/payouts`)
  appends a path.
- `Path.from_file_url` takes a `Url` and `Path.to_file_url` gives one, as in Effect.

### Changed

- Every place Effect reads a date with JavaScript's `Date` (`config.date_time`, the CLI's
  `date` flags and arguments, cookie `Expires`, `S.DateTimeUtcFromString` and other
  `DateTime.make` strings, `make_zoned_from_string`, TOML date-times) now reads it as V8 does,
  so more strings are accepted: `Jan 15 2024 10:00 PM EST`, `1/15/2024`, `2024-02-30` (March
  1st), leading spaces. `config.date_time` now reads a date-time without an offset as local
  time, as Effect does; it read it as UTC before. Parsed values are UTC `datetime`s in whole
  milliseconds.
- `path.win32` (and `path.layer_win32`) follows Node's `path.win32` on any host instead of
  Python's `ntpath`: `join("C:\\a", "\\b")` is `C:\\a\\b`, `relative(p, p)` is `""`,
  `resolve` uses a drive's own working directory (`=D:`), and reserved device names (`CON:`)
  and `toNamespacedPath` work as in Node. `path.format` adds the dot to an `ext` without one,
  and both services have `delimiter`.
- `date_time.zone_named` names a zone with ICU's canonical id, as Effect's `zoneMakeNamed`
  does under Node: `Asia/Kolkata` is `Asia/Calcutta`, `EST` is `America/Panama`, `Etc/UTC` is
  `UTC` (ICU 78.3). An offset id (`+0530`) is the fixed zone `+05:30`, as in `Intl`. An id ICU doesn't know,
  such as `Factory`, is no longer a zone. `TZ` and
  the system zone read the same way.

### Fixed

- A `Host` (or `X-Forwarded-Host`, or an absolute request target) whose host the URL parser
  rejects, such as `999.0.0.1`, is no longer accepted as an authority, as Effect's
  `isValidHost` rejects it.
- An absolute request target sets the request's host to the URL's normalized host (lowercase,
  default port dropped), as Effect's Node server does.

## 0.2.0 (2026-11-09)

### Breaking

- A bare number as a duration is now milliseconds, as in Effect; in 0.1.0 it was seconds.
  `fx.sleep(5)` used to wait 5 seconds and now waits 5 milliseconds. This applies everywhere a
  `Duration` is taken: `sleep`, `delay`, `timeout` and its variants, schedules (`spaced`,
  `exponential`, `fixed`, `during`, `up_to(duration=)`), `TestClock.adjust`, cache, pool and
  `RcMap` times to live, and the timeouts and intervals of the HTTP, SQL, RPC, cluster,
  workflow and observability layers. Strings, `timedelta`s, `(seconds, nanos)` pairs and unit
  mappings are unchanged.

  To migrate, search your code for these calls with a bare number (and for functions that
  return one, such as a `time_to_live` callback or a `modify_delay` function), then either
  write the unit (`fx.sleep("5 seconds")`, `"500 millis"`, `timedelta(minutes=1)`) or multiply
  by 1000. Units read the same in both versions, so code written with them works before and
  after upgrading.

- Durations pyfect hands back are `Seconds`, which pass through unchanged when given as a
  duration: `Effect.timed()` and `clock.timed` now pair the value with `Seconds` (was a plain
  `float`), as do a schedule's `Metadata.elapsed` and `elapsed_since_previous` and a
  transaction's `elapsed`. Arithmetic that keeps the unit stays `Seconds` (`d * 2`, `d + d`,
  `d / 2`); adding a bare number gives a plain `float`.

- Timestamps given or read as a bare number are epoch milliseconds, as in Effect; in 0.1.0
  they were epoch seconds:
  - `testing.set_time(timestamp)` and `TestClock.set_time` (Effect's `TestClock.setTime`) take
    milliseconds: `set_time(5)` was 5 seconds after the epoch and is now 5 milliseconds.
    `TestClock(start=)` takes milliseconds too.
  - `clock.now()` and `ClockService.now_unsafe()` (seconds) are replaced by Effect's
    `clock.current_time_millis()` and `current_time_millis_unsafe()` (milliseconds). The old
    names are gone, so code that used them fails loudly; a custom `ClockService` renames its
    `now_unsafe` method and returns milliseconds.
  - A schedule step's `now` argument and its `InputMetadata` / `Metadata` `start` and `now`
    (`schedule.from_step`, `to_step`, `tap`, `modify_delay`, `CurrentMetadata`) are
    milliseconds, as are a transaction's `TransactionMeta.start` and `now`.
  - `metric.summary_with_timestamp` reads the timestamp of each `(value, timestamp)` as
    milliseconds.

  To migrate, multiply epoch seconds by 1000 (`set_time(dt.timestamp() * 1000)`); a test that
  hands `datetime.timestamp()` or `time.time()` straight to `set_time` is the usual case.
  `clock.now_nanos`, `monotonic`, `monotonic_nanos`, `FileSystem.utimes` (seconds, as Node's
  `fs.utimes`) and the durations above are unchanged.

- `eventlog.event_log_session_auth.SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_SECONDS` (30.0) is now
  `SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_MILLIS` (30000), Effect's
  `SessionAuthChallengeTimeToLiveMillis`.

- A missing service fails with Effect's message, `Service not found: <key>` (was
  `Service <key> was not provided`). Code or tests that match the old text need updating.

- `PubSub` wakes takes parked on several subscriptions in the order they parked, and orders
  back-pressured publishers and takers as Effect does. Code that relied on the old order may see
  messages arrive in a different order.

### Added

- `duration.from_input`, Effect's `Duration.fromInput`: `None` for a string that is not a
  duration.
- `duration.millis_to_nanos`: the whole nanoseconds in a count of milliseconds, read exactly.
- Custom `PubSub` strategies, as in Effect: `PubSub.make` takes any `pubsub.Strategy`, and
  `BackPressureStrategy`, `DroppingStrategy` and `SlidingStrategy` are built on the same
  interface. The strings `"suspend"`, `"dropping"` and `"sliding"` still work.

### Fixed

- A `(seconds, nanos)` pair whose total overflows to infinity is infinite, and a unit mapping of
  whole units sums them exactly, as in Effect.
- `PubSub.shutdown` interrupts a publisher that can never be let in; before, it waited forever.
  Publishing thousands of messages at once to a back-pressured `PubSub` works (Effect's
  strategy overflows the stack there).
- Schema's defect JSON writes the error's `name`, as Effect does.
- A write to a child process's `stdin` after it closed fails with Node's error for the case:
  `write after end`, `Premature close`, or `EPIPE` from `write`.
- With a schema compiler installed after a parser was built, a `Union` member the parser had
  not reached yet uses the compiled decoder, as in Effect.

## 0.1.1 (2026-11-07)

New, as in Effect:

- Effect's own OTLP exporters for logs, traces and metrics, next to the OpenTelemetry SDK bridge.
- Schema decoders compiled at run time (JIT) or ahead of time, and Standard Schema support.
- The rest of Effect's Schema test titles, with their behaviour.

Fixed:

- Sockets wait for the peer to read when a write fills the buffer, instead of buffering without
  limit; TLS over TLS works; a pipe write is no longer cut short.
- The terminal reads keys the way Node does, including a lone Escape after 50 ms.
- ASGI WebSockets follow the ASGI state order, and a mounted app's HEAD, 204 and 304 responses
  carry no body.
- A PostgreSQL connection lease is returned exactly once.
- MCP: a repeated `initialize` keeps the agreed protocol, a batch after close is refused, and a
  duplicate request id is refused, as in Effect.
- A `Cache` whose `time_to_live` function raises ends the lookup with that error as a defect
  and keeps nothing (Effect hangs here). The multipart parser rejects malformed input instead
  of crashing.

## 0.1.0 (2026-11-07)

The first release of pyfect on PyPI, as `pyfect-dev` (import `pyfect`).

pyfect is Effect for Python. It follows Effect v4.0.6 and does what Effect does wherever
Python can express it. It needs Python 3.13 or later, and its types check under pyright strict.

It includes the fiber runtime with structured concurrency and interruption, errors as values
with `Cause`, services and layers, resources and scopes, streams, schedules, STM, Schema,
configuration, observability (logs, traces and metrics, with OpenTelemetry), testing support,
and the platform libraries: HTTP client and server, HTTP API, RPC, SQL drivers, cluster and
workflows, the event log, AI and MCP, and the CLI. Guides and the API reference are at
[pyfect.dev](https://pyfect.dev).

Where pyfect differs from Effect, and why, is listed in `docs/PARITY.md`. Three differences
matter most:

- A bare number as a duration, as in `fx.sleep(5)`, is seconds here and milliseconds in Effect.
  A later release changes it to milliseconds, as a breaking change. Write `"5 seconds"` or a
  `timedelta` to keep code working across that change.
- pyfect keeps security protections Effect lacks: body and header limits, `Origin` and redirect
  checks, CORS with credentials, log and SSE line injection, cookie and session limits, redacted
  names and SQL string parameters.
- pyfect does not copy seven behaviours of Effect that look like bugs.

### If you installed pyfect from GitHub before 0.1.0

These changes from earlier commits match Effect and can break code written against them:

- `run_sync` of an effect that doesn't finish synchronously, such as one that waits on a
  worker, a socket or a sleep, now fails with `AsyncFiberError` as a defect, like Effect's
  `runSync`. Use `run_blocking` (or `run_blocking_exit`) for those. A worker's entry point
  that called `run_sync` on its main effect now exits at once, and the client sees only
  "exited with code 0".
- A model call naming a tool the toolkit doesn't have fails as
  `LanguageModel.generateText: Invalid output`, without the tool's name, as in Effect.
