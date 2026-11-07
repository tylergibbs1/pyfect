# Changelog

## 0.2.0 (unreleased)

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

- `eventlog.event_log_session_auth.SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_SECONDS` (30.0) is now
  `SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_MILLIS` (30000), Effect's
  `SessionAuthChallengeTimeToLiveMillis`.

### Added

- `duration.from_input`, Effect's `Duration.fromInput`: `None` for a string that is not a
  duration.

### Fixed

- A `(seconds, nanos)` pair whose total overflows to infinity is infinite, and a unit mapping of
  whole units sums them exactly, as in Effect.

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
