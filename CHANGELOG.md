# Changelog

## 0.4.0 (unreleased)

### Breaking

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

### Added

- `Pool.stats()` returns a `PoolStats` (idle, used, pending, `min`, `max`).
- `stream.ignore`, `ignore_cause` and the channel ones take `log="Unhandled"` to log at the
  fiber's `UnhandledLogLevel` (nothing when it is `None`).
- `cron.DstOverlapPolicy` (`"earlier"`, `"later"`, `"both"`).

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
