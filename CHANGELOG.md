# Changelog

## 0.5.5 (unreleased)

### Changed

- `router.provide_request(services)` is typed as Effect's `HttpRouter.provideRequest`: the
  result drops each `Requires[S]` that `services` builds and adds `services`' own errors and
  requirements (it was `Layer[Any, Any, Any]`, so even `provide_request(layer.empty)` passed).
- `router.to_asgi` takes only routes whose requirements its layer builds, as Effect's
  `toWebHandler` needs them built by the app layer when there is no request context: a missing
  service, or `layer.provide(services)` where `provide_request(services)` belongs, is a pyright
  error instead of a 500 on every request. A routes layer still needing a service to build is
  refused too, as is a `middleware=` needing one. Runtime behaviour is unchanged. A helper
  generic in its services' type (`def app_routes[RO](services: Layer[RO])`) keeps its routes'
  `Requires`, since pyright can't see which ones `RO` builds (TypeScript resolves Effect's
  `Exclude` at each call): type the helper with its layer, or apply `provide_request` outside it.
- `fx.blocking` / `fx.try_blocking` run on daemon threads that exit after 10 seconds idle,
  where a `ThreadPoolExecutor` kept every thread for the process's life and joined them at
  exit. Effect has no thread pool (Node runs such work on libuv's), so this follows Python's
  norm for work a program may abandon: a process whose blocking work was interrupted, and is
  still running, now exits at once instead of waiting for it.

### Added

- Guide: [Adopting in an asyncio app](/docs/asyncio-apps): a `ManagedRuntime` in the app's
  lifespan, mapping typed errors at the seam (`run_async` takes only `Never` errors), sharing
  layers between runtimes with `memo_map`, which `contextvars` cross `run_async`, `from_async`
  and a fork, `router.provide_request`, routes mounted with `to_asgi`, and `hypercorn_server`
  with the legacy app mounted through `from_asgi`. HTTP server links to it.

### Fixed

- `hypercorn_server` no longer prints hypercorn's own "Running on" line: the listen log is
  `serve`'s alone, so `disable_listen_log=True` leaves out every startup line, as with Effect's
  `NodeHttpServer`, which logs nothing itself.
- `router.add_all([...])` takes a list mixing routes of different error or requirement types:
  `Route` is now covariant (pyright inferred a frozen dataclass's parameters as invariant), so
  such a list matched no overload.

## 0.5.3 (2026-11-10)

### Changed

- `router.in_memory_client` and `router.layer_in_memory_client` make every failure of the
  routes a defect of the request, as Effect's `HttpApiTest` client does (`Effect.orDie`): a
  route not found dies with its `HttpServerError` (`RouteNotFound`) and a body over the limit
  with `RequestParseError`, where they used to come back as 404 and 413 responses. Payloads and
  path parameters failing their schema were already defects. A test reads them with `.exit()`.
  `http_api.test.groups` now builds on `router.in_memory_client`, so the two cannot drift.
- `layer.merge` takes any number of layers (Effect's `mergeAll` is variadic); past five, the
  outputs, errors and requirements still join.
- `MacService`, `DigestService` and `JwksService` keep their constructors but hold their
  operations as documented methods, so `help()` and `inspect.signature` show them; every crypto
  service's operations have docstrings, as do `fx.run_blocking`, the other run functions and
  every other function `pyfect` exports.

### Added

- Cryptography guide: envelope encryption (`KeyWrap` with a key from Argon2id through `Kdf`), sealing
  to an X25519 public key with HKDF, expiring EdDSA tokens (`iat` / `exp` with
  `required_claims`), the JWK thumbprint as `kid`, and key sets that change (`jwks.make_local`
  per request, `JwksService(resolve=...)` refusing a revoked `kid`).
- Testing: in-memory responses carry cookies in `.cookies`, not `set-cookie` headers, as in
  Effect. CLI: `literals` keeps its literal type for a tuple of choices.

### Fixed

- `jwt.sign` and `jwt.encrypt` check `claims` against the schema's Type, as Effect's
  `S["Type"]` does: `{"sub": 1}` for `sub: str` is a type error (it used to widen the Type).
- `Mac.generate_key` returns `Key[A]` for the algorithm's type `A`, as `Aead` and `KeyWrap` do
  (it returned `Key[Any]`).
- `router.layer_in_memory_client` takes routes that need services (`Requires[...]`): they become
  the layer's requirements, as with `serve`, and a service the request provides itself comes
  first.
- Typed errors become defects only where Effect elects them: after a failed body's finalizer
  fails, when every racer of a race fails, and when a concurrent `for_each` adds a later
  failure to its first. Closing a scope now fails with its finalizers' causes as they are
  (concatenated, as Effect's `Exit.asVoidAll`: a typed failure stays a `Fail` beside a
  defect, and equal failures are kept), and so does `scoped` / `ensuring` / `on_exit` after
  a successful body. A race every racer lost keeps equal failures (still electing defects).
- An interrupted `callback` whose canceler fails reports the interruption first, then the
  canceler's cause (Effect's `combineFinalizerCause`).
- `HttpApiClient`: an error response whose decoder dies keeps its `StatusCodeError` a typed
  failure beside the defect.
- The live HTTP server writes a streamed body as Effect does (`Stream.orDie`), so its failure
  after the head is a defect, combined with the response without electing.
- MCP: a `resources/read` failing with a typed error beside a defect and an interruption
  answers the whole cause with the error still a failure, as the other requests do (it went
  through a `catch_tag`, which elected the defect; Effect maps the error instead).

### Deprecated

- `cause.merge` (it elects defects, and Effect has no such combinator): combine causes with
  `a + b`, Effect's `Cause.combine`. It goes in 0.6.0.

## 0.5.2 (2026-11-10)

### Added

- `mcp_server.layer_rpc_protocol(...)` and `mcp_server.run(...)` serve MCP over any RPC server
  transport, the `rpc.server.ServerProtocol` in the context (Effect's `McpServer.layer` and
  `McpServer.run`). A transport with `supports_notifications=False` gets no notifications and
  serves no subscriptions, as in Effect.
- `rpc.server.ServerProtocolService` and `ProtocolParts` take `supports_notifications`
  (default `True`; the HTTP protocol sets it from its serialization's framing) and
  `client_ids` (the connected clients, reported by the built-in transports; default `None`,
  not reported). `rpc.server.WriteRequest` is exported.
- The ClickHouse client takes `@clickhouse/client`'s transport options, under the same names,
  as Effect's `ClickhouseClientConfig` passes them through: `compression` (request and
  response, gzip, zstd or br), `keep_alive`, `max_open_connections`, `tls` (a CA, and a
  client certificate), `use_multipart_params` / `use_multipart_params_auto`, `log` and
  `json`, with their URL parameters (`compression_request`, `compression_response`,
  `keep_alive_enabled`, `keep_alive_idle_socket_ttl`, `max_open_connections`, `log_level`),
  which used to fail as not offered. Their types are in `pyfect.sql.clickhouse.options`.
- The `watch` extra (`uv add "pyfect-dev[watch]"`, on watchfiles): `FileSystem.watch` on
  `file_system.layer` / `platform.layer` uses the operating system's change notification
  (inotify, FSEvents, ReadDirectoryChangesW) through `file_system.WatchfilesBackend`, as Effect's
  Node file system uses `fs.watch`, so changes arrive as they happen and a file created and
  removed at once is still reported. Events follow Effect's: an entry that appeared or went
  away is `Create` if it exists afterwards and `Remove` if not, a changed one is `Update`,
  paths are relative to the watched directory. The watcher runs on its own thread, stopped and
  joined when the stream closes. Without the extra, `watch` polls every 50 milliseconds as
  before; a provided `WatchBackend` still comes first.

### Changed

- The httpx client the ClickHouse layer makes now uses `@clickhouse/client`'s pool defaults:
  at most 10 connections, idle ones closed after 2.5 seconds (httpx's were 100 and 5
  seconds). Pass `max_open_connections=` or `keep_alive={"idle_socket_ttl": ...}` to change
  them.
- As `@clickhouse/client` does, the ClickHouse client logs a failed request at `ERROR`, a
  failed `/ping` at `WARN`, and warns when the URL overrides a config field or when
  `request_timeout` is over a minute without progress headers. `log={"level": "OFF"}`
  silences it.

### Fixed

- An MCP request whose failure also holds an interruption (middleware that adds one) is
  answered as Effect answers it: `{"_tag": "Cause", "code", "message", "data"}` with the
  serialized cause in `data`, an internal error for a legacy `tools/call`, and an internal
  error for an interruption alone, which before got no answer.
- `zip.decode` fails on corrupt deflated data as Effect does: an entry `zlib` rejects, that
  ends early or that grows past its `size` is replayed through a port of Effect's inflater,
  so the error has Effect's kind and message (`"InvalidData"` where it gave `"Truncated"` or
  `"SizeMismatch"` before, and Effect's wording instead of zlib's). Body chunks are cut where
  Effect cuts them (every 64 KiB of output and where the input runs dry). At most 4 MiB of an
  entry's compressed input is kept for the replay; a corrupt entry longer than that fails with
  Effect's kind and zlib's message, as before.
- `mcp_test.make_client` writes every message as JSON text and reads it back, both ways, as
  the stdio and HTTP transports do and as Effect's `McpTest` does, so a test sees what a wire
  client sees: a tool's `structuredContent` holds lists where it held the server's tuples, and
  a server reads a test's request as a transport delivers it. `mcp_test`, stdio and HTTP
  share one encoding, and the in-memory client can only read encoded messages.
- `FileSystem.watch` without the `watch` extra reports a batch's removals first, as the native
  watcher does, so a rename is `Remove` of the old name then `Create` of the new one whichever
  name sorts first.

## 0.5.1 (2026-11-10)

### Added

- `S.HashSet(item)` and `S.HashMap(key, value)` (Effect's `Schema.HashSet` / `Schema.HashMap`)
  decode to `pyfect.hash_set.HashSet` / `pyfect.hash_map.HashMap`, so `1` and `True` are two
  items or keys and every `NaN` is one, as in Effect. `S.FrozenSet` / `S.Map` still decode to
  `frozenset` / `dict` and refuse input those would merge. JSON writes a set as an array of its
  values and a map as an array of `[key, value]` pairs, in Effect's order; ISO, Hypothesis
  strategies, equivalence, formatter, JSON Schema, representation (`R.hash_set_reviver`,
  `R.hash_map_reviver`) and generated code follow Effect's. `HashSet[X]` / `HashMap[K, V]`
  annotations derive them in `S.Struct` and schema classes.

### Fixed

- The observability guide passed a seconds histogram to `track_duration` without a mapping,
  which fails on 0.5.0; it now shows Effect's form,
  `track_duration(histogram, duration.to_seconds)`. Self-contained inline code in the guides
  is now type-checked (`tests/test_doc_inline_code.py`).
- A format spec on a `Duration` (`f"{d:g}"`) names the conversion to use in its `TypeError`.

## 0.5.0 (2026-11-10)

Durations are exact. `duration.Duration` is Effect 4.1.2's `Duration`: whole nanoseconds at
any length, or infinity, compared and hashed as Effect's are. It replaces the float-based
`duration.Seconds` everywhere pyfect handles time, and `Schema.Duration` decodes to it.
Every API still takes the same inputs (bare numbers are milliseconds, `"5 seconds"`,
`timedelta`, ...). The renames are listed below with how to migrate.

### Changed (breaking)

- `duration.Duration` is now Effect's `Duration` value: an immutable, hashable, final class
  holding whole milliseconds, whole nanoseconds or an infinity (its `.value` is `Millis`,
  `Nanos`, `Infinity` or `NegativeInfinity`), with Effect's arithmetic, equality, order,
  `format`, `format_iso`, `parts`, `to_hr_time` and `to_json`. It replaces `duration.Seconds`,
  a `float` of seconds that rounded past 2**53 ns and had no exact sub-microsecond or huge
  values. `fx.Duration` is this value type. Everything that took or returned `Seconds` (sleeps,
  timeouts, `Clock.sleep`, `Scheduler.call_later`, schedule delays and `Metadata` fields,
  `timed`, `TimeoutException.duration`, TTLs, the schema duration codecs) takes or returns a
  `Duration`. Migrate:
  - The input alias `duration.Duration` (number, string, `timedelta`, pair, mapping) is now
    `duration.Input`; annotate parameters `duration.Input` and parse them with
    `duration.from_input_unsafe(x)` (was `duration.to_seconds(x)`). `duration.to_seconds(x)`
    now returns a `float` of seconds, as Effect's `toSeconds`.
  - Build durations with `duration.millis(n)`, `nanos(n)`, `micros`, `seconds`, `minutes`,
    `hours`, `days`, `weeks`, `zero`, `infinity` and `negative_infinity`. `Duration(x)` is a type
    error and raises `TypeError`. `ZERO` is `zero`; `from_nanos(n)` is `nanos(n)`;
    `from_millis(n)` is `millis(n)`.
  - A `Duration` is no `float`: `d * 1000`, `d + 0.5`, `d < 1.0` and `float(d)` are type
    errors, and `d == 0` is always false (pyright reports it, but not `0 == d` or a
    comparison with an untyped value, which are silently false too). A format spec such as
    `f"{d:g}"` raises `TypeError` at run time, and pyright doesn't check format specs. Use `d.to_seconds()`,
    `d.to_millis()`, `d.is_zero()`, `d.is_finite()`, `d < duration.seconds(1)` or
    `d.to_timedelta()`. `+`, `-`, `*` by a number, unary `-`, `abs`, `<` and friends work
    between durations; `d.divide(n)` returns `None` where Effect's `divide` returns `None`.
  - `format_duration(d)` is `d.format()`; `format_iso(d)` is `d.format_iso()` (both are
    Effect's: `format` prints a long count of days as a JavaScript number).
  - `to_nanos(x)` returns `None` for an infinite duration (Effect's `toNanos`); use
    `to_nanos_unsafe` to raise. `nanos_or_infinite` takes a `Duration`, and
    `from_nanos_or_infinite` is its inverse.
  - `DurationParts` is `DurationObject` (Effect's `DurationObject`); `Parts` is what
    `d.parts()` returns.
  - `add_nanos`, `millis_to_nanos`, `round_nanos` and `parse_duration_text` are gone: add
    durations, and parse text with `from_input` / `from_input_unsafe`.
  - A schedule step's `elapsed` and `elapsed_since_previous`, and `TransactionMeta.elapsed`
    and `elapsed_since_previous`, are float milliseconds (`now - start`), as in Effect (they
    were `Seconds`): `m.elapsed / 1000` for seconds, `duration.millis(m.elapsed)` for a
    `Duration`. `fixed`, `windowed`, `during`, `up_to(duration=)` and `cron` compute with
    Effect's float milliseconds and JavaScript's `%`.
  - `Schema.Duration` holds a `duration.Duration`, and the codecs `DurationFromString`,
    `DurationFromNanos`, `DurationFromMillis` and `DurationFromIsoString` decode to one, as
    Effect 4.1.2's do: infinities and sub-microsecond values decode, and the "Expected a
    duration a timedelta can hold" limits are gone. Infinities fail to encode as nanoseconds
    or ISO text. A `duration.Duration` annotation derives `S.Duration`; a `timedelta`
    annotation no longer does (annotate `duration.Duration`, and call `d.to_timedelta()`
    where a `timedelta` is needed). The JSON form is Effect's (`{"_tag": "Nanos", "value":
    "1500000"}`), and the binary form is Effect's tags.
  - `AiError.retry_after`, `RateLimitError.retry_after` and parsed `Retry-After` headers are
    `Duration`s.
  - Two `Millis` durations add as JavaScript numbers do, as in Effect: the sum rounds past
    2**53 ms and saturates to `infinity` past float range; anything with a `Nanos` side adds
    exactly.

## 0.4.1 (2026-11-10)

### Added

- The cluster guide has a Kubernetes section (`runner_address` from the pod IP,
  `runner_listen_address`, the `k8s` health check, RBAC, CA trust, shutdown and an example
  manifest) and documents `entity_resource` and `make_k8s_pod`. The installation and
  PostgreSQL guides say psycopg needs libpq.

### Changed

- The `brotli` extra installs brotlicffi instead of Google's `brotli`, whose C module turns
  the GIL back on for the whole process on a free-threaded CPython (3.14t), and httpx imports
  it whenever it is installed. Every extra now keeps the GIL off on 3.14t, which
  `tests/test_free_threaded.py` checks. If another dependency still installs `brotli`, httpx
  loads it instead; the installation guide shows how to check.

### Fixed

- Importing a module whose extra is installed but fails to import (psycopg without the libpq
  C library, as on slim Docker images) no longer says to install the extra: the `ImportError`
  shows the library's own error, and chains it. Only a library that is not installed gets
  the install command. The same holds for the `regex` fallback of schema patterns, which used
  to refuse `\p{...}` silently when an installed `regex` failed to import.
- `entity_resource.make_k8s_pod(spec)` is typed with `k8s_types.Pod`, under its own name (it
  was an alias named `PodSpec`, read as `k8s_types.PodSpec`): it takes a whole pod manifest,
  as Effect's `makeK8sPod(spec: K8sPod)` does. The same misleading alias is gone from
  `k8s_http_client.CreatePod`.

## 0.4.0 (2026-11-10)

pyfect now follows Effect 4.1.2 (it followed 4.0.6). Every test title Effect 4.1.2 added is
ported or listed with its reason in `docs/PARITY.md`. New in this release: the `crypto` and
`jose` modules (the `crypto` extra), MCP Skills and server middleware, HTTP `ProblemDetails`,
`Glob`, the CSV, JSON5 and JSONC encodings, `process.command_line`, the persistence
`CircuitBreaker`, and the encrypted event log's compaction protocol. Many changes follow
Effect 4.1.2 and break code written against 0.3; each is below with how to migrate.

### Breaking

- RPC `client.rpc.discard(payload)` no longer completes when the request is written: as in
  Effect 4.1.2 it sends `discard: true` and completes once the server acknowledges the call
  (a successful exit sent as its handler starts, after the middleware ran), so a middleware
  error or a failure before the handler starts now fails it; its error type is the method's
  `E | TE` (it was `TE`). An older server answers with the handler's result, which also
  counts as the acknowledgement. `rpc.client.OnFromClient` has no `discard` field any more:
  a discarded call is a `Request` with `discard=True`, and a custom `on_from_client` passed
  to `make_no_serialization` must answer it with a successful `ResponseExit` once the request
  is delivered (a transport that only delivers requests acknowledges it itself), or the call
  waits. `message.Request` has new `is_notification` and `discard` fields.
- An RPC server sends nothing for a request with `isNotification` (a JSON-RPC notification):
  no exit, chunk or defect, and its failures are only reported; a notification for an unknown
  method, with an invalid payload or malformed headers is dropped and logged at debug level.
  It used to be answered like a call with the empty id. Notifications get ids of their own, so
  overlapping ones all run.
- The worker RPC client protocol fails only the calls on a worker that crashed (its
  `ClientProtocolError` lists them in `requestIds`); it used to fail every pending call of the
  client.
- A GraphQL response with a status that is not 2xx never succeeds, even with `partial=True`:
  it fails with a `ResponseError` when its body has `errors`, and otherwise with a
  `TransportError` carrying the status, headers and `Retry-After` (a 2xx response without
  data or errors is still a `DecodeError`).
- `rpc.RpcClientError`, `rpc.RpcClientDefect`, `socket.SocketError` and its reasons
  (`SocketReadError`, `SocketWriteError`, `SocketOpenError`, `SocketUpgradeError`,
  `SocketCloseError`) are schema classes, as in Effect, so they encode and take keyword
  arguments only: `RpcClientError(reason=RpcClientDefect(message="bad"))`,
  `SocketError(reason=SocketCloseError(code=1006))`. An RPC call over HTTP now fails with an
  `RpcClientError` whose reason is the new `http.error.HttpClientErrorSchema` (the HTTP
  error's `kind`, with its reason as the `cause`; `HttpClientErrorSchema.from_http_client_error`)
  instead of the `HttpClientError` itself. `RpcClientErrorReason` now includes the worker
  error reasons. `AtomRpc` queries that fail with an `RpcClientError` are now kept by
  `hydration.dehydrate`. A worker error reason without a `cause` encodes without the key (it
  was `null`), as Effect's.
- `process.make(..., shell=True)` with arguments fails with `BadArgument` when spawned, as
  in Effect 4.1.2: the command is the whole script. pyfect used to quote each argument onto
  the shell line; build the script with `process.command_line.join([...])` (or `quote`) and
  pass it alone, or drop `shell`. `make`'s command and arguments are positional-only
  (`make("ls", ["-l"])`; `args=` is gone), because `make` also takes a template now
  (`make(["git commit -m ", ""], message)`, or a t-string on 3.14). Errors name a command
  through `command_line.display`: arguments are shell-quoted, `Redacted` ones masked and
  control characters escaped (`echo 'a b'`, not `echo a b`). `ChildProcessHandle.stdin` is a
  `Sink[None, bytes | str, ...]` (text is encoded with `StdinConfig.encoding`), so a
  hand-built handle's `stdin` must accept `str` too.

- `key_value_store.make` and `make_string_only` take a required `keys` (an effect giving a
  snapshot of the keys, Effect 4.1.2's `keys`) and an optional `clear_prefix`, which is
  derived from `keys` and `remove` when omitted; a hand-built store must pass `keys`. Every
  store has `keys` and `clear_prefix(prefix)`. A prefixed view (`store.prefix(p)`) now
  scopes `keys`, `size`, `is_empty` and `clear` to its prefix, as in 4.1.2: `clear` on a
  view removes only its own keys (it cleared the whole store), so
  `persistence.layer_backing_kvs` stores clear only their own entries. The file-system
  store's `remove` succeeds for a missing key (it failed with `NotFound`).
- `encoding.toml.parse` returns a `Result` (`Ok(dict)` or `Err(EncodingError)` with module
  `"Toml"` and Effect's message) instead of raising `ValueError`, as Effect 4.1.2's
  `Toml.parse` does: replace `toml.parse(text)` with `toml.parse(text).get_or_raise()` to
  keep raising (now the `EncodingError`), or match on the result. TOML is also read more
  strictly, as in 4.1.2: a table defined by dotted keys cannot be redefined by a header, an
  inline table or array cannot be extended, dates and times out of range (`2026-02-30`,
  `24:00:00`, an offset of `+24:00`) and integers past 2**53 - 1 are errors, raw control
  characters and a bare carriage return are errors, and up to two quotes before a multiline
  string's closing delimiter belong to its content. `cli.primitive.file_parse` reports a
  bad TOML file as `EncodingError: ...` (it said `SyntaxError: ...`).
- `encoding.yaml.parse` reads an unquoted `<<` key as a YAML 1.1 merge key, as Effect 4.1.2
  does: it merges a mapping (or a list of them) into the enclosing one, where it used to be an
  ordinary `"<<"` key. Quote it (`"<<": ...`) to keep the old reading.

- `FileSystemService` has a new abstract `read_directory_entries(path)`, giving each name
  with the type of the entry itself (`file_system.DirectoryEntry`), and `glob` is no longer
  abstract: it is built from `read_directory_entries`, `stat` and `read_link`, as Effect
  4.1.2's `FileSystem.make` builds it. A `FileSystemService` subclass must implement
  `read_directory_entries` (one wrapping another file system can delegate it; one that
  reports no types can give `"Unknown"` for every entry) and can drop its `glob`
  (`NoopFileSystem` already does both). `glob` now follows Effect's (and `pyfect.glob`'s)
  pattern rules instead of Python's `glob.glob`: results are `/`-separated even on
  Windows, depth first with each directory's entries sorted by name, `dir/**` includes
  `dir`, `**` does not follow symbolic links to directories, an unreadable directory
  named by the pattern fails the glob, and the new `dot=True` matches names that start
  with `.`.
- `TerminalService` has a required `size` field: an `Effect[Dequeue[Size, Done], Never,
  Scope]` whose queue holds the current `terminal.Size` and then the latest size after
  each resize until its scope closes (Effect 4.1.2's `Terminal.size`). A hand-built
  terminal (in tests, say) must pass one, for example a queue holding one
  `Size(80, 24)`.
- `Trie` stores the empty string key like any other, as Effect 4.1.2 does: `insert("", v)`
  adds it (it was ignored), it iterates first, counts in `len`, and `longest_prefix_of`
  falls back to it. Code that relied on `""` being dropped must skip it itself.
- `big_decimal.from_string` gives `None` for a scale past 10,000 or a normalized scale below
  -10,000 (it accepted any safe-integer scale) and for a fraction that is not digits
  (`".-1"`); arithmetic that has to align scales more than 20,000 digits apart (`sum`,
  `subtract`, `remainder`, `rescale`, `truncate`, `round`) raises `ValueError`, as Effect
  4.1.2's `RangeError`. Build very large or very small values with `big_decimal.make`.
- `json_patch.apply` rejects a JSON Pointer with a `~` not followed by `0` or `1`
  (`Invalid JSON Pointer escape`); it read `~2` as a literal.
- CLI help lists a subcommand's own flags under `FLAGS` and the shared flags of its
  ancestors under a new `INHERITED FLAGS` section, as Effect 4.1.2 does; they were listed
  first under `FLAGS`. `HelpDoc.flags` from `help_for_path` no longer holds the inherited
  flags: read `HelpDoc.inherited_flags` for them (also new: `command_path` and
  `global_flags_scope`). A custom `Formatter` must render `inherited_flags` to keep them
  in its help.
- `sse.Event` accepts an `event` or `id` holding `\r` or `\n` (it raised `ValueError`, and
  `encode_schema` failed with a `SchemaError`); `sse.write` removes them, and NUL from the
  id, as Effect 4.1.2's encoder does. Code that relied on the error to reject such values
  must check them itself.
- `Semaphore` serves waiters in the order they asked, as Effect 4.1.2 does: a fiber that
  releases its permits and takes again goes behind those already waiting (it could take
  them straight back), and a waiter keeps its place until it takes its permits. Code that
  relied on a holder reacquiring at once must not.
- `PartitionedSemaphore` gives a partly served waiter the permits released next until its
  request is whole, before turning to the next partition (it gave one permit per
  partition per turn, so two multi-permit waiters could each hold some and deadlock).
- `cron.prev` of a time a DST gap skipped returns the matches before that time, as Effect
  4.1.2 does (it could return the gap's shifted wall time). A wall time a DST change
  repeats still runs once, at its first occurrence; pass `on_dst_overlap="later"` or
  `"both"` (new on `cron.make`, `cron.parse`, `cron.parse_unsafe` and `schedule.cron`) to
  change that. `Cron` equality now includes `on_dst_overlap`.
- `schedule.cron` waits for the next match when the delay to the current one rounds to
  zero (it ran twice), and schedule elapsed times are rounded to the nanosecond, as
  Effect's `Duration` (a `fixed` or `windowed` schedule waits a full window when the delay
  to its boundary rounds to zero).
- `Pool.make` and `make_with_ttl` run in a child of the current scope, so a finalizer added
  to that scope after the pool can still borrow from it.
- `Stream.rechunk` and `group_adjacent_by` emit the elements they hold before failing (they
  were dropped), and `group_by` ends its open groups when the upstream fails or ends.
- `date_time.start_of`, `end_of` and `nearest` below a day keep a time in the repeated DST
  hour in that occurrence (they could move it to the other one).
- Defects of resources released in the background (`RcMap` and `RcRef` idle expiry and
  interrupted lookups, `ScopedCache` expiry) are logged at `UnhandledLogLevel` ("Unhandled
  error in RcMap finalizer") instead of being lost.
- An atom build that releases a failed earlier build reports that build's finalizer error
  once the new build commits (it was raised in the middle of the rebuild).
- AI, Effect 4.1.2: `ai_error.NetworkError` has `method: str`, `url: str` (without URL
  parameters) and an optional `cause` instead of `request`. Read `err.method` / `err.url`
  instead of `err.request["method"]` / `err.request["url"]`; build one with
  `NetworkError(reason=..., method=..., url=...)`, or `NetworkError.from_http_client_error(error)`
  to keep the HTTP client error as `cause`. `ai_error.HttpRequestDetails`,
  `HTTP_REQUEST_DETAILS` and `HttpMethod` are removed and `HttpContext` has no `request`: read
  `http["response"]` / `http["body"]`, and log the request yourself if you need it. Status
  mappers of the providers take `method=` and `url=`.
- AI: `response.ResponseMetadataPart` no longer has `request` (decoding ignores the key), and no
  provider's response-metadata parts carry the request.
- AI decisions: provider answers are plain dicts tagged by `_tag`:
  `ProviderClassifyAnswer("x", probs)` becomes
  `{"_tag": "Classify", "label": "x", "probabilities": probs}`; likewise `"Rate"` (`rating`),
  `"Probability"` (`probability`), `"Locate"` (`box` as a `{left, top, right, bottom}` dict,
  `confidence`) and `{"_tag": "Refusal"}`. `decision_model.ProviderBoundingBox` is new.
- Anthropic: `tool.ComputerUse_20241022` is named `computer` on the wire (was `computer_use`).
  `TextEditor_20250429` and `TextEditor_20250728` decode inserts as `InsertTextCommand`
  (`params["insert_text"]`), not `InsertCommand` (`new_str`, kept for the older versions).
  `ToolSearchRegex_20251119` takes `ToolSearchRegexParameters` (`pattern`, optional `limit`) and
  `ToolSearchBM25_20251119` `ToolSearchBM25Parameters` (`query`, optional `limit`) instead of
  `QueryParameters`. `language_model.Model` lists 4.1.2's model names (`claude-opus-4-1` is
  gone); any string is still accepted.
- MCP server: the registration layers `mcp_server.toolkit`, `resource`, `resource_template`,
  `prompt` and `skill` require `McpServer`. Give them to the transport,
  `layer_http(..., registrations=toolkit(...))` (also `layer_stdio`), or write
  `registrations.pipe(layer.provide_merge(transport))`, instead of
  `layer.merge(transport, toolkit(...))`.
- MCP server: a defect in a handler or middleware answers `{"code": -32603, "message":
  "Internal error"}` (was `Internal server error`); match on the code.
- MCP server: a declared tool failure is sent through its schema's JSON codec, as in Effect
  4.1.2: a `BigInt` is a string, and a `Redacted` field's value is sent. Keep secrets out of
  declared failure fields, or declare them with `S.Redacted(..., disallow_json_encode=True)`
  so encoding refuses them. A result that fails to encode is an `AiError` with a
  `ToolResultEncodingError` reason. Resource and template listings always carry
  `annotations`.
- MCP client: `mcp_client.toolkit(..., failure_mode="return")` sends the model the encoded
  `McpClientError` (`{"_tag": "McpClientError", "reason": {...}}`) and the result is the
  `McpClientError`, not its text; tool failures have the `McpClientError` schema (was
  `Unknown`). Read `result.reason` (a `ToolError`'s `result["content"]`), or reshape with
  `transform_tool`. A resource link with an empty `title` reads `": <uri>"`, as in Effect.
- Observability: OTLP/JSON writes `bytesValue` as base64 text. `otlp_resource.from_config`
  trims `OTEL_RESOURCE_ATTRIBUTES` keys and values and keeps `key=` as `""`;
  `otel.resource.layer_from_env` does too, percent-decodes keys and values, accepts a
  structured config record, and drops the whole variable with a warning when its encoding is
  malformed (write a literal `%` as `%25`).
- `pyfect.crypto` is now Effect 4.1.2's `effect/crypto`, a package with one service per
  family, and needs the `crypto` extra (`pip install "pyfect-dev[crypto]"`). The 4.0.6
  `Crypto` service, `CryptoService`, `crypto.make`, `crypto.layer` and the module-level UUID
  helpers are gone, and `fx.platform.layer` no longer provides crypto. Migrate:
  - `Crypto().random_bytes(n)`, `random_uuid_v4()`, `random_uuid_v7()`, `random_ulid()` and
    the shuffles: `SecureRandom()` from `pyfect.crypto.secure_random`, with `random_bytes(n)`,
    `uuid_v4()`, `uuid_v7()`, `ulid()`, `int_between(...)` and `shuffle(...)`. UUIDs take
    `format="string"` (was `"hex"`) or `"bytes"`.
  - `Crypto().digest(algorithm, data)`: `Digest()` from `pyfect.crypto.digest`, with
    `digest(digest.sha256, data)`.
  - `Crypto().random()` and the other number draws: `fx.Random`.
  - Provide `pyfect.crypto.native.layer` (or one family's `native.layer_*`) where
    `platform.layer` provided `Crypto`. Failures are `CryptoError`, not `PlatformError`.
- `testing.TestCrypto` is removed; Effect 4.1.2 has no seeded crypto service. Use
  `fx.Random` with a seed for reproducible numbers, or `web_crypto.layer(fake)` to replace
  the Web Crypto implementation under every `layer_web_crypto` service.
- The `Model.UuidV7Insert` generator makes monotonic UUIDv7s from the `Clock`, as Effect's
  `Uuid.v7Monotonic` does: ids made in the same millisecond increase strictly.
- `Base64Url` decoding follows Effect 4.1.2: padded input must be a whole number of 4-character
  groups, and the error messages name the padded or unpadded length rule.
- `circuit_breaker.Classify` is renamed `Classifier`, and a classifier takes
  `(exit, context)`: `context` is a `ClassifyContext` whose `probe` is `True` for the
  half-open probe, as in Effect 4.1.2. Migrate `lambda exit: ...` to
  `lambda exit, _context: ...`. `http.client.circuit_breaker_classifier` accepts the context
  and can still be called with the exit alone.
- `rate_limiter.make_store_memory()` is replaced by `rate_limiter.make_memory_store`, an
  effect needing a `Scope` that gives a `MemoryRateLimiterStore` whose expired keys a scoped
  fiber sweeps every minute (Effect's `makeMemoryStore`). Write
  `yield from rate_limiter.make_memory_store` inside a scope.
- `RateLimiter.consume` with a `limit` of zero or less no longer reaches the store: `"fail"`
  rejects a positive request and `"delay"` gives an infinite `delay` and `reset_after`.
- The Redis and KVS `BackingPersistence` backends store entries under `<store_id>:<key>`,
  with `%` and `:` in the store id percent-encoded; the Redis rate limiter percent-encodes
  `%` and `:` in keys. Entries and counters written by earlier versions under such keys
  (all KVS entries) are no longer found; persisted caches recompute them.
- The Redis `PersistedQueue` store records each claim under a lock key unique to its
  acquisition, in `<prefix><name>:owners`, as Effect 4.1.2 does. Stop older workers and let
  their locks expire before starting upgraded workers on the same prefix.
- `event_log_encryption.make_encryption_subtle(crypto)` takes a
  `pyfect.crypto.web_crypto.Crypto` (Effect's `makeEncryptionSubtle(crypto)`) instead of an
  `AesGcm` cipher; the `AesGcm` protocol and `EventLogEncryptionService.sha256_string` are
  removed. Wrap the Web Crypto object to count or replace AES-GCM, or use
  `event_log_encryption.layer` with your own `Aead`, `Digest` and `SecureRandom` layers; use
  `(yield from encryption.sha256(data)).hex()` for the hex digest. The `eventlog` extra now
  also installs PyNaCl.
- The event log server verifies the presented signing key before binding it, and keeps the
  Hello challenge on the connection: one use, released on disconnect, 30 seconds from
  generation. A client reusing a challenge, or sending one from an earlier connection, gets
  "Session auth challenge has expired".
- `event_journal.make_entry_id_unsafe(msecs=)` clamps out-of-range timestamps as Effect's
  `v7Bytes` does, instead of raising `OverflowError`.
- An eventlog compactor (the `CompactFn` given to `register_compaction`) must accept a keyword
  `remote: bool = False`, `True` during a remote compaction, which only drops entries:
  `def compact(entries, write, /, *, remote=False): ...`. `RegistryService.remotes` is a
  `Mapping[RemoteId, EventLogRemoteService]`, as in Effect 4.1.2; iterate `.values()`.
- `sql_event_log_server_encrypted.make_storage` / `layer_storage` require
  `pyfect.crypto.digest.Digest` instead of `EventLogEncryption`, as in Effect 4.1.2: provide
  `digest.layer_web_crypto`, or use `layer_storage_subtle`, which provides it.
- The encrypted event log server serves 4.1.2's compaction RPCs
  (`EventLogEncryptedServerRpcs` = `EventLogRemoteRpcs` + `EventLogCompactionRpcs`), and
  `Hello` answers `compaction=True` when the storage compacts; both built-in storages do (tune
  them with `layer_storage_memory_with({...})` or `layer_storage(compaction={...})`; invalid
  options die with `IllegalArgumentError`). `StorageService` has a new
  `compaction: StorageCompaction | None` attribute; custom storages keep working without
  compaction. The SQL storage creates `<prefix>_compaction_{stores,buckets,activations,stages}`
  and a `<table>_snapshot` table per store, seeds stores written by older versions on first
  open, prunes originals once a snapshot is past `grace` (30 days by default), and omits a
  write's acks for ids at or below the active snapshot's base.
- Inside a workflow, awaiting a child workflow that is interrupted fails the parent with a
  defect (`<Tag>.execute: execution "<id>" was interrupted`) instead of interrupting it, as
  in Effect 4.1.2. Use `.catch_defect(...)` or `.exit()` on the child's `execute` to recover.
- `ShardingConfigService` has a new required field `runner_join_debounce: Seconds` (Effect's
  `runnerJoinDebounce`, 0 in `DEFAULTS` and `layer`); code building `ShardingConfigService(...)`
  directly must pass it.
- The SQL runner storage with advisory locks has the server end a lock session left idle for
  `shard_lock_expiration` (releasing its locks), and a refresh no longer re-takes locks lost
  with an earlier session, as in Effect 4.1.2. A persisted request's final reply is stored
  only after a lock refresh confirms this runner still owns the shard; otherwise the request
  is left to the shard's new owner.
- `HttpClientService.with_cookies_ref` takes a `Ref[tuple[Cookie, ...]]` (Effect 4.1.2's
  `Ref<ReadonlyArray<Cookie>>`) instead of a `Ref[Cookies]`, and stores each cookie with its
  domain, path and `host_only` flag, as `cookies.merge_into_array` does. Make the jar with
  `Ref[tuple[Cookie, ...]].make(())`; to seed it, merge `Set-Cookie` values for the URL they
  belong to: `cookies.merge_into_array((), "https://api.example.com", cookies.from_set_cookie("token=foo; Path=/"), now)`.
  A cookie put in the jar without a `domain` is never sent (it used to go to every request);
  a `Secure` cookie from an `http` response is kept (sent only over `https`); cookies are
  selected for a request's final URL, after `map_request` / `prepend_url` applied after
  `with_cookies_ref`, and stored for the response's final URL. Same-name cookies for
  different paths are all sent, longest path first.
- `cookies.from_set_cookie` trims only spaces and tabs around a cookie's name and value, and
  ignores a `Max-Age` that is not an optional `-` followed by digits (`1.5`, `+5` and `0oops`
  were read as `1`, `5` and `0`), as Effect 4.1.2 does.
- `HttpClientRequest.method` and `ServerRequest.method` are typed `str`, not `HttpMethod`, as
  in Effect 4.1.2: a received request keeps an extension method such as `PROPFIND`, and so
  does a client request converted from it. Code that passes a request's method where an
  `HttpMethod` is expected narrows it first with `method.is_http_method(m)`;
  `method.has_body` takes any `str` (narrowing only an `HttpMethod`). `set_method` and
  `request.make` still take an `HttpMethod`.
- `HttpClientRequest.compress_body` keeps the request's own `content-type` header (an
  explicit one, or none) and only updates `content-length` and adds `content-encoding`; it
  used to reset `content-type` from the body. Set the header yourself if you relied on that.
- `follow_redirects` removes `content-encoding`, `content-language` and `content-location`
  with the body when a redirect switches the request to `GET`, and aborts each discarded
  redirect response instead of leaving its connection to be released when collected.
- `body.File.content` is a `body.FileContent`: `bytes` or a function opening a byte stream
  (a form file read on demand), no longer always `bytes`. Code reading `file.content` as
  bytes handles both: branch on `isinstance(file.content, bytes)`, or read
  `file.stream()` (a `Stream[bytes, FileSourceError]`) for either kind, e.g.
  `file.stream().run_collect().map(b"".join)`. Constructing a `File` from bytes is unchanged.
- `http_api.builder.layer` fails (a defect) when two endpoints share a method and path, as
  Effect 4.1.2 does; the second was unreachable before. Declare one endpoint whose query,
  headers, payload or success schemas cover each variant.
- `openapi.from_api` requires every stacked security middleware: an endpoint behind
  middlewares `A` and `B` lists `[{a: [], b: []}]` where it listed `[{a: []}, {b: []}]`
  (either one). Several schemes of one middleware are still alternatives. Nothing to change
  in code; clients generated from the spec now send every credential.
- `StreamSse(data=...)` encodes and decodes `data` with the schema's JSON codec
  (`to_codec_json`), as Effect 4.1.2 does, so a date is an ISO string and a big integer a
  string on the wire. Events whose data schema had no JSON form used to fail; a client and
  server on different versions disagree on such fields.
- An endpoint may declare an upgrade beside ordinary successes, as in Effect 4.1.2; what is
  still rejected (a second upgrade, a `101` or streaming sibling, a streaming payload or
  `HEAD`) has new messages, and the old "Cannot combine an upgrade with another success
  response" is gone. Beside other successes, a handler that calls `ctx.upgrade()` must return
  nothing (`.map(lambda _: None)`); returning a value after upgrading is a defect.
- HTTP server errors (`RouteNotFound`, `RequestParseError`, `ResponseError`, ...) name only the
  request path in their message, as in Effect 4.1.2: `RouteNotFound (GET /widgets)` where it
  was `RouteNotFound (GET /widgets?token=REDACTED)`; an absolute request URL shows its pathname.
  Read `error.request.url` when you need the query. A synthesized 5xx span error keeps the
  redacted URL.
- `url_params_body` on server requests and client responses keeps a leading `?` and a leading
  byte order mark as form data (`??a=1` reads as `("??a", "1")`, not `("?a", "1")`), as Effect
  4.1.2 does. Strip them yourself if a peer sent them by mistake.
- Trace headers are parsed as Effect 4.1.2 parses them: W3C `traceparent` and B3 ids with
  uppercase hex, and W3C flags that are not exactly two lowercase hex digits, are rejected
  (no parent span). The sampled flag is bit 0 of the flags (`03` is sampled).
- `url_params.CurrentRedactedNames` redacts `X-Amz-Signature`, `X-Amz-Credential` and
  `X-Amz-Security-Token` by default too. Set the reference to drop them if you log them.
- `static_server` answers `If-Match` and `If-Unmodified-Since` that fail with 412 before
  checking `If-None-Match`, `If-Modified-Since` and ranges, and its 304 repeats
  `Cache-Control`, `Content-Location`, `Date`, `ETag`, `Expires`, `Last-Modified` and `Vary`.
- The live server's WebSocket frame parser closes a frame with RSV1 set (and no
  `permessage-deflate`) with 1002 and the message "RSV1 must be clear"; other reserved bits
  give "RSV2 and RSV3 must be clear".
- A socket reader's pull returns at most `chunk_size` chunks (4096 by default, `math.inf` for
  no limit), as Effect 4.1.2's `NodeSocket` does; it returned everything buffered. Pass
  `chunk_size=math.inf` to `make_net` / `make_tls` / `from_socket` to keep the old batching.
- SQL, Effect 4.1.2: `migrator.from_file_system` moved to the new module
  `pyfect.sql.migrator_file_system` (`from pyfect.sql.migrator_file_system import
  from_file_system`), so `pyfect.sql.migrator` no longer imports the file-system loader; the
  driver migrators (`pyfect.sql.sqlite.migrator.from_file_system` and the others) still
  re-export it.
- SQL: a transaction's `BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT`, `RELEASE SAVEPOINT` and
  `ROLLBACK TO SAVEPOINT` are client spans under its `sql.transaction` span (named `COMMIT`
  or `COMMIT <db.namespace>`, with `db.operation.name`), as in 4.1.2, instead of events on
  it; a tracer that read those events must read the child spans. The connection wait
  (`db.client.connection.wait_time_ms`) is recorded on the transaction span only with
  `SpanPropagationEnabled` and `TracerTimingEnabled`. Rollbacks and savepoint releases of
  cleanup always run unprepared.
- libsql: `LibsqlSdk` has a required `protocol` (`"http"`, `"ws"` or `"file"`); a hand-built
  SDK (a test fake) must set it. Remote statements (`http`/`ws`) no longer wait for each
  other or for an open transaction, as in 4.1.2; local ones still run one at a time.
- ClickHouse: the migrator writes its ledger (the table and the inserts) with
  `ClientMethod` `"command"` and runs migrations as queries, as in 4.1.2's
  `Migrator.make({ transformWrites })` (new: `migrator.make(transform_writes=...)`); the
  `INSERT ... SELECT ... UNION ALL` workaround is gone.
- MySQL: a text-protocol statement (`disable_prepared_statements=True`, and every stream)
  writes a list parameter as `1, 2` (a nested list as `(1, 2), (3, 4)`) and a dict in a `SET`
  / `ON DUPLICATE KEY UPDATE` list as `` `key` = value `` pairs, as mysql2 does; both were
  JSON text. Prepared statements still bind them as JSON. To keep sending JSON over the text
  protocol, pass `json.dumps(value)`.
- MySQL: a `mysql://` URL's query is read as mysql2 reads it: `ssl` (a JSON object such as
  `?ssl={"rejectUnauthorized":false}`) and `connectTimeout`; other options are refused when
  the config is made (all query parameters were).
- PostgreSQL: `PgClientService(...)` takes a required `pool_stats` (a hand-built client must
  pass one), and a pin released inside an aborted transaction it did not open closes its
  session instead of handing it back to the pool. A prepared statement the backend lost
  (`26000`, a transaction pooler moved the session) or whose plan went stale (`0A000`) is
  parsed again and the statement retried once, unless the transaction is already aborted.

### Added

- The live server takes `websocket_per_message_deflate=True` (or a
  `live_server.PerMessageDeflate(...)`) to accept WebSocket `permessage-deflate` offers, as
  Effect's `NodeHttpServer` with `ws`'s `perMessageDeflate`; the inflated size counts against
  `websocket_max_message_size`. `mime` knows `py` (`text/x-python`) and `sh`
  (`text/x-shellscript`).
- RPC (Effect 4.1.2): `serialization.json_rpc` / `nd_json_rpc` / `layer_json_rpc` /
  `layer_nd_json_rpc` take `control_messages=False`, which reads `@effect/rpc/*` methods as
  ordinary notifications for plain JSON-RPC peers; `ServerOptions(on_disconnect=...)` is
  called with each client id the transport reports disconnected; a `ClientProtocolError` can
  name the `requestIds` it fails. JSON-RPC stream chunks of a batched request go out at once
  instead of waiting for the batch's exits, and a stream consumer that stops early sends no
  more `Ack`s.
- `pyfect.http.problem_details` (Effect 4.1.2's `ProblemDetails`): the RFC 9457 `Schema`,
  which drops wrong-typed members and keeps extensions, and `to_response`.
- `http_api.error.Problem`: `class OutOfCredit(Problem, type=..., status=..., title=...)` is a
  typed `application/problem+json` error decoded by its `type`; `BadRequestProblem` and
  `InternalServerErrorProblem`. `middleware.ProblemDetails` with
  `layer_problem_details(include_details=)` turns request schema errors into a problem 400
  (with `errors` when asked) and response encoding errors into a reported problem 500.
  `schema.as_problem(title=)` sends an existing error as a problem.
- Stream schemas take a list of content types (`content_type=["a", "b"]`, stored as
  `content_types`, the first is the default): a stream payload accepts each, a client decodes
  whatever arrives, OpenAPI lists each. An empty or duplicate list raises `ValueError`.
- `http_api.client.decode_response(api, group, endpoint)` decodes a response obtained with
  `response_only` later, like the method would; `client.is_upgraded(value)`.
- HTTP upgrades on the httpx client (Effect's `HttpClientResponse.upgrade`): a request made
  with `request.upgrade("tcp")` no longer fails before it is sent, and the `101` response's
  `upgrade` is the connection as a `Socket`, the bytes the server sent past the head first.
  Releasing the reader's scope closes it, the writer's half-closes it; any other status fails
  with a `StatusCodeError`. A derived `HttpApiClient` decodes a `101` into an `Upgraded`
  (`client.is_upgraded`), closing the connection if its headers fail to decode.

- `HttpClientService.timeout(duration)` (Effect 4.1.2's `HttpClient.timeout`): a request
  without a response in time fails with an `HttpClientError` whose `TransportError` is caused
  by a `TimeoutException`, which `retry_transient` retries. Applied before `retry_transient`
  each attempt gets its own budget; after it, one budget covers the retries.
- `request.from_web(web_request)` (Effect's `HttpClientRequest.fromWeb`): a client request
  sending what a `WebRequest` received, its body as a `Raw` body.
- `body.update_content_length(headers, body)`.
- A form file's content (`body.File(content, ...)`) can be a function opening a byte stream
  (a web `File`'s `stream()`) as well as `bytes`: the httpx client reads it on demand as the
  connection takes it, stops it when the request is interrupted or aborted, and fails with a
  `TransportError` when the function raises or the stream fails (`body.FileSourceError`
  carries the cause), as Effect 4.1.2's `NodeHttpClient` does. `File.stream()` gives the
  content as a stream; `body.File.content` is typed `body.FileContent`.

- `Pool.stats()` returns a `PoolStats` (idle, used, pending, `min`, `max`).
- SQL: `PgClient.pool_stats` and `PgPool.stats` (a `make_client` client reports its one
  session as leased), `migrator.TransformWrites` and `migrator.make(transform_writes=)`.
- MySQL: TLS from a URL (`?ssl={...}` as mysql2's `ssl` object).
- `stream.ignore`, `ignore_cause` and the channel ones take `log="Unhandled"` to log at the
  fiber's `UnhandledLogLevel` (nothing when it is `None`).
- `cron.DstOverlapPolicy` (`"earlier"`, `"later"`, `"both"`).
- `cookies.merge_into_array` and `cookies.to_request_cookie_header` (Effect 4.1.2's RFC 6265
  client storage) and `CookieOptions.host_only` (`serialize_cookie` leaves out `Domain` for a
  host-only cookie).

- `pyfect.glob` (`fx.glob`), Effect 4.1.2's `Glob`: `glob.make(pattern, dot=)`,
  `glob.match` / `Glob.match` and `glob.escape`, the patterns `FileSystem.glob` walks
  with (braces, bracket and POSIX classes, `**`, a trailing `/` for directories, linear
  wildcard matching).
- `FileSystem.read_directory_entries` and `glob(dot=)`; `make_temp_directory_scoped` and
  `make_temp_file_scoped` no longer die when their directory was already removed.
- `Terminal.size` and `terminal.Size`: the terminal's size, then each resize.
- `schema_binary.int32`, `uint32`, `int64` and `uint64`: integers written as four or eight
  little-endian bytes, and `schema_binary.to_codec_strict`, which rejects unknown fields,
  keys, union members and field wire kinds instead of skipping them.
- `cli_output.default_formatter(inherited_flags=, global_flags=)`: `"full"`, `"summary"`
  (a pointer to the declaring command's help) or `"none"`.
- Bash completion of file and directory values keeps a path with spaces as one argument
  and an expandable or quoted directory as typed.
- `ndjson` `ignore_empty_lines=True` also skips lines of only spaces and tabs.
- `S.is_ascii()` (with `representation.is_ascii_reviver`), `S.DurationFromIsoString`
  (`"PT1H30M"` to a `timedelta`; years and months rejected) and
  `transformation.duration_from_iso_string`.
- `getter.split_key_value` / `transformation.split_key_value` take `trim=` and
  `keep_empty_values=`.
- `json_schema.to_document_draft_07_with_definitions_path` and
  `json_schema.to_multi_document_components`; an empty `enum` becomes
  `{"allOf": [{"not": {}}]}` in Draft-07, which requires a non-empty one.
- A tagged schema class's `make` fills in `_tag` when given plain fields, and uses a
  constructor installed for the class (`S.make_class_sync`, Effect's `makeClassSync`).
- `Model.UuidV7Insert` ids sort in the order they are made, also within a millisecond or
  under a `TestClock`.
- Importing JSON Schema intersects an `anyOf` sibling's `enum` with a branch's (Effect
  issue 10047), where it raised `RepresentationError`.

- `ignore(log="Unhandled")` / `ignore_cause(log="Unhandled")` log at the
  `UnhandledLogLevel`, and not at all when that is `None`.
- `Fiber.interrupt_as(by, annotations)` adds annotations to the interruption.
- `duration.to_micros`, `duration.format_iso` and `duration.from_iso` (ISO 8601 durations).
- `byte_size`'s decimal units scale the shortest decimal form exactly, so
  `megabytes(2.01)` is 2,010,000 bytes (it failed on the float product).
- MCP Skills (`io.modelcontextprotocol/skills`): `mcp_server.skill(uri, files)`, and on the
  client `extensions={"skills": True}` with `list_skills`, `get_skill`,
  `read_resource_directory` and `read_skill_resource` (digest-checked); client
  `discovery_limits` and per-call `limits=`.
- MCP server: `mcp_server.middleware`, `visibility`, `Middleware.layer` / `layer_global` /
  `combine`, `cache_hints=` (2026-07-28 `ttlMs`), and `pyfect.ai.mcp_test.make_client`.
- MCP client: `toolkit(tools=, result_mode="complete", failure_mode=, trust_annotations=,
  timeout=, transform_tool=)`, `ToolDescriptor`, `RemoteTool`, schemas for `McpClientError`.
- Anthropic: `tool.DeferLoading`; non-strict tools may have recursive parameters.
- `config.dict_of(..., trim=, keep_empty_values=)`.
- The crypto families of Effect 4.1.2: `secure_random`, `digest`, `mac`, `kdf` (HKDF, PBKDF2,
  Argon2id), `aead` (AES-GCM, ChaCha20-Poly1305, XChaCha20-Poly1305), `cipher` (AES-CBC /
  CTR), `signature` (Ed25519, ECDSA, RSA-PSS, RSASSA-PKCS1-v1_5), `key_agreement` (X25519,
  ECDH), `key_wrap` (AES-KW, RSA-OAEP), `key_format` (SPKI, PKCS#8, PKCS#1, SEC1, JWK, PEM),
  `web_crypto` and `native`, all on `cryptography` and PyNaCl.
- `pyfect.crypto.schema`: Effect's crypto key schemas (`MacKeyFromBytes`,
  `SignaturePublicKeyFromFormat`, ...).
- `pyfect.jose` (`fx.jose`): `jwk`, `jwks`, `jws`, `jwe` and `jwt`, interoperable with Node's
  `jose`.
- Docs: [Cryptography and JOSE](/docs/crypto).

### Fixed

- `net.dns.layer_system()`'s `reverse` returned the query name (`8.8.8.8.in-addr.arpa`) among
  an address's names, and answered from the hosts file: it read `gethostbyaddr`. As Effect's
  `NodeDns`, it now asks the name servers in `/etc/resolv.conf` for PTR records and returns
  their targets (`dns.google.`). The system `resolve` answers PTR queries (other types still
  fail with `Unsupported`), and `make_system` / `layer_system` take `name_servers=`.
- Anthropic: a response holding code execution 20250825's `bash_code_execution` /
  `text_editor_code_execution` blocks failed with `InvalidOutputError`; the calls now decode as
  `AnthropicCodeExecution` calls. A chat that used code execution, web fetch or an MCP server
  sent the results back as user `tool_result` blocks, which Anthropic rejects with 400
  "unexpected `tool_use_id`"; every server tool result is now provider-executed and replayed in
  the assistant message as Anthropic sent it, a 20250522 error result included. Effect 4.1.2
  has both bugs (docs/PARITY.md section 4).
- `GenerateTextResponse` and `GenerateObjectResponse` are covariant, so a response of one
  toolkit can be typed as one of a wider toolkit; `tool_calls` and `tool_results` are typed
  `Sequence` (still lists).
- Docs: the `http.template` / `html_template` docstrings and the HTTP server guide say that
  values are not HTML-escaped (as in Effect), and the guide says that what
  `serve(middleware=...)` returns is dropped, as in Effect, pointing at
  `router.middleware(f, global_=True)`. The `UserDirectories` example provides
  `user_directories.layer`, and the `encoding.toml` docstring no longer calls its differences
  from `tomllib` a feature. New guides: data formats (TOML, YAML, INI, `semver`,
  `big_decimal`), user directories, Anthropic provider tools and the tokenizer.

## 0.3.1 (2026-11-09)

### Added

- `Semaphore.take_scoped(n)`, Effect 4.1.2's `takeScoped`: waits for `n` permits and holds
  them until the current scope closes.

### Fixed

- A large write to a child's stdin no longer hangs on free-threaded CPython: the pipe's
  writer thread kept a `memoryview` made on the fiber's thread, and 3.14t can release a
  buffer whose views are made and freed on different threads, so about one 24 MB write in
  twenty died with "operation forbidden on released memoryview object". The writer thread
  now makes and releases its own views, and a writer thread that raises fails the write
  (a defect) instead of leaving it waiting.
- A write to a child's stdin made before pyfect has handled the child's exit fails with
  `ECANCELED` every time, as in Effect 4.1.2 under Node; it sometimes failed with
  `Premature close`. The exit now closes stdin in a task of the run's scheduler, as Node
  does in a turn of its event loop, and a write first tries the pipe at once, as Node's
  does, so a small write made then succeeds.
- Docs that still read a bare number as seconds now give units: `set_idle_ttl` in the
  atoms guide, `window` in the rate-limiting guide, `schedule.StepFn`'s `now` (epoch
  milliseconds), the `schedule` module's examples and metadata, `session_idle_timeout`,
  and the examples of `testing`, `layer_map`, `layer_ref`, `workflow`, `durable_clock`
  and the rate limiter.

## 0.3.0 (2026-11-09)

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
- Standard Schema: the props live at the spec's `~standard` attribute
  (`getattr(adapted, "~standard")`); `adapted.__standard__` is now a read-only typed alias of
  it. `json_schema.input` / `output` take the spec's options, `input({"target": "draft-07"})`,
  instead of `target=`, and `validate(value, options=None)` accepts the spec's second argument.
- `schedule.fibonacci(one)` waits `one`, `one`, `2*one`, `3*one`, `5*one`, ..., as Effect 4.1.2
  does; it skipped the second `one`.
- `EventLogServerAuthorizationService.authorize_identity` also receives
  `signing_public_key`, the key the client presented, as Effect 4.1.2's `authorizeIdentity`
  does; implementations must accept it. `event_log_session_auth.derive_signing_public_key`
  gives an identity's key, so a server can record it at provisioning and reject any other.
- `workflow.make` takes only a struct schema or a schema class as `payload` (Effect's
  `Schema.Struct.Fields | AnyStructSchema`): any other schema is a type error and raises
  `TypeError` at definition, where the cluster engine used to die at run time.
- `decision_model.decide` / `decide_settled` no longer take `images=`: images go in the input
  as `decision.Image` fields (values are `decision_model.Image`), and `ProviderOptions.images`
  holds `ProviderImage(reference, path, image)` with the state carrying each reference, as in
  Effect 4.1.
- `atom.serializable(schema=...)` is typed against the atom's value, so a schema of another
  type is a type error (Effect's `ConstraintCodec<Type<R>>`).

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

- The OTLP exporters arm their interval with the first buffered item and stop it once an
  export empties the buffer, as Effect 4.1.2 does: a span ended at 2 seconds goes out at 7, and
  an idle exporter keeps no timer.

### Added
- A schema class (`S.Class`, `S.TaggedClass`, `S.Error`, `S.TaggedError`) has `ast`, as every
  Effect schema does, so `jit_compiler.enable(User.ast)` and `aot_compiler.Target(User.ast, ...)`
  take it. A field named `ast` is still the instance's.
- `telemetry.CurrentSpanTransformer` (Effect's `Telemetry.CurrentSpanTransformer`): a
  language model calls it with the options it sent and the response's parts after
  `generate_text` / `generate_object` and when a `stream_text` stream ends.
- `decision.locate`, `decision.Image`, `BoundingBox`, `LocateAnswer` and
  `decision_model.make(supports_locate=)` (Effect 4.1). TypeSafe decision models take images
  and locate decisions (`jev-1.14.0`); OpenAI and Cloudflare decision models label images by
  reference.
- `tool.make(to_model_output=)` / `tool.dynamic(to_model_output=)`, `prompt.ToolModelOutputPart`,
  `prompt.tool_model_output_to_text` and `model_output` on tool results, carried into the
  follow-up prompt (Effect 4.1). Anthropic and OpenAI send native content blocks;
  OpenAI-compatible providers and OpenRouter send text.

### Fixed
- An OTLP exporter paused for a minute after a failed export dropped every item pushed after
  the minute until some export ran; the first push after the minute now ends the pause, as in
  Effect 4.1.2.
- `pyfect.pydantic.from_model` reports only the first pydantic error unless decoding with
  `errors="all"`, as every schema does.
- A `Model.Class` field outside the `select` variant wrapped in `Model.field(...)` failed with
  dataclasses' "is a field but has no type annotation"; it now names the fix (assign the variant
  field without `field(...)`).
- A persisted chat's `stream_text` is saved to the store when the stream ends, as Effect's
  `Stream.ensuring(saveChat)`; it stayed in memory only.
- `registry.subscribe` builds the atom, as Effect 4.1.2 does, so a subscriber of an atom no
  one has read hears its next change and an effect atom starts.
- A graph's default node and edge labels are JavaScript's `String(data)`: a list is `1,2`, not
  `[1, 2]`. `String(...)` ports everywhere (schema coercion, INI values, CLI messages) write
  lists and dicts as JavaScript does.
- Anthropic strips a `data:` prefix from PDF data as well as images, and OpenAI sends PDFs
  given as base64, data-URL or https strings, as Effect 4.1.2 does.
- A rate limiter's whole `remaining` is an `int` from every store; Redis gave `1.0` where the
  memory store gave `1`.
- A `Host` (or `X-Forwarded-Host`, or an absolute request target) whose host the URL parser
  rejects, such as `999.0.0.1`, is no longer accepted as an authority, as Effect's
  `isValidHost` rejects it.
- An absolute request target sets the request's host to the URL's normalized host (lowercase,
  default port dropped), as Effect's Node server does.
- `http_api.test.groups` and `router.in_memory_client` bound a whole-body read by
  `MaxBodySize`, as the network servers do: a payload past 10 MiB is refused instead of
  decoded and handled. `ServerRequest.bytes_` is now final; a request type implements
  `_read_whole(max_bytes)`, so none can skip the limit.
- `live_server` reads a chunk size line as Node's `llhttp` does: whitespace around the size
  or an extension (`2 `, `2;a b`), an empty extension name (`2;;`), an unterminated quoted
  value, `2;a=b=c` and a size past 64 bits are a 400. `2 ;name` was accepted before.
- Interrupting a MySQL statement sends `KILL QUERY` over a one-off connection and waits for
  the statement to stop, so the connection, and any transaction on it, goes on, as
  `@effect/sql-mysql2` does. The connection is closed and `KILL`ed only if the statement
  hasn't stopped within five seconds.
- Where Effect writes JSON with `JSON.stringify` (MCP tool results, request bodies, protocol
  frames), pyfect writes a `Redacted` value as `<redacted>`, as its `toJSON` does in Effect;
  it raised `TypeError`. An MCP declared failure
  without a message with a `Redacted` field is now sent with `"<redacted>"` there instead of
  as an internal error.

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
