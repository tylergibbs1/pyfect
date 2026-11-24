# Changelog

## 0.6.32 (2026-11-24)

0.6.31 was tagged but never published: a test timed out in its release run. 0.6.32 carries its changes.

### Added

- `telegram_chat.escape_markdown(text)` and `teams_chat.escape_markdown(text)` turn text a user
  wrote, such as a display name, into Markdown that shows it as typed, so a name like
  `[x](https://evil.example)` is no longer a live link in a post. A dogfood app had that
  injection. WhatsApp needs none: it has no link markup and no escape character, which its docs
  page now says.
- `teams_chat.layer`, `whatsapp_chat.layer` and `telegram_chat.layer` (and `whatsapp_graph_api`'s
  and `telegram_bot_api`'s `make` and `layer`) take `max_retry_after`, passed to
  `chat_adapter.retry_safe`. A 429 asking to wait longer fails the op at once with
  `RateLimited`, its `retry_after` the wait the platform asked for, instead of holding the op,
  and whatever queues behind it, for as long as the platform says; Teams can ask for an hour.
  Without it any wait is waited out, as before and as in Effect. Every adapter now reads a
  `Retry-After` (or Discord's and Telegram's `retry_after`) through one shared parser.
- `chat_adapter.retry_safe` takes `max_retry_after`: a `retry_after` longer than it is not
  waited out, and the `ChatError` comes back at once with the wait on it, for the caller to
  decide. The default, `None`, waits out any wait, as Effect's `retrySafe` does.
- `discord_chat.layer` takes `max_retry_after`: a 429 asking to wait longer fails `RateLimited`
  at once, its `retry_after` on the error, instead of holding the request (and whatever queues
  behind it) for as long as Discord asks; its shared limits can ask for over 20 minutes. By
  default any wait is still waited out, as in Effect, whose Discord adapter and dfx's REST
  client wait without a bound.

### Fixed

- `discord_chat.command_requests` raises `ValueError` naming a command or option whose name
  Discord refuses (`^[-_ʼ\p{L}\p{N}\p{sc=Deva}\p{sc=Thai}]{1,32}$`, lowercase where a
  letter has a lowercase), or whose description is not 1 to 100 characters, instead of
  building a list Discord rejects as a whole when it is registered. Effect builds the list
  unchecked.
- The Discord gateway's websocket (`discord_gateway.layer_ws`) reconnects as soon as Discord
  closes the connection, instead of only at the shard's next write, up to a heartbeat interval
  (about 41 seconds) later: each connection's read and write loops now end at the first exit
  (`race_first`), not the first success. dfx, which Effect's Discord adapter runs on, reads in
  the connection's own loop and never had the delay. `tests/test_chat_race_guard.py` keeps
  `race` out of the chat adapters.
- A dispatch the Discord `DispatchHook` refused is no longer lost when the next dispatch was
  already read: the shard used to hand that one to the hook and store its sequence, so the
  RESUME asked for what came after it. As in dfx (which Effect's Discord adapter runs on), once
  the shard drops a connection it skips whatever is still queued from it until the next HELLO,
  sends no heartbeat in between, and stores a `READY`'s session only after the hook took it.
- `telegram_chat.layer_polling` gives each `getUpdates` its long poll plus 3 seconds to answer,
  then gives it up and retries it with `chat_adapter.retry_safe`'s backoff. A connection that died
  without a reset (a NAT entry gone, a proxy that stopped answering) left the call waiting forever,
  and the bot never read another update; Effect's adapter has the same hang. The layer's first
  call has the 3 seconds too. `TelegramBotApiService.call` takes a `timeout` for this: a request
  without an answer by then fails `Transport` with detail `timeout`.
- A Telegram command answer refused for being private (`chat_interaction.respond` and `defer`
  default to `visibility="ephemeral"`, which the adapter has no way to send) fails `Unsupported`
  with detail `ephemeral`, so the `chat_interaction` log line reads
  `telegram.respond: Unsupported: ephemeral` instead of a bare `Unsupported` that did not say what
  was missing. The Telegram docs say to answer with `visibility="public"`.
- `telegram_chat.layer_webhook` hands commands and button clicks to the `chat_interaction.Handler`
  its layer was given. It read the handler from each request's context, where it is not, so a
  command fell through to the `ChatHandler` as an ordinary message and a click was answered and
  dropped, with nothing logged; polling, whose fiber is forked in the layer, worked. Both
  transports now take the `ChatHandler` and the `chat_interaction.Handler` from the layer when it
  is built, and run updates through one function that is given both.
- The WhatsApp adapter waits out a rate-limited answer's `Retry-After` before it sends again, as
  the Teams and Slack adapters do, and keeps it as the `RateLimited` error's `retry_after`. It
  ignored the header and retried after its own backoff from half a second, while Meta still
  refused.

### Performance

- The Telegram and WhatsApp webhooks count a body's nesting before parsing it about three times
  faster on bracket-heavy bodies: the brackets are packed eight to a byte, so the running sum
  takes one step per eight. The count now lives in one place, `pyfect.chat._json_depth`, shared
  with the Discord adapter.
- The Discord adapter's check that a gateway frame, interactions request or REST answer nests
  at most 64 deep, made before each parse, no longer walks every character in Python: a body
  with no more than 64 opening brackets (almost every frame) passes after two counts, about
  25 times faster, and any other is counted with the shared `pyfect.chat._json_depth`, about 2
  times faster on Discord's own payloads and 5 times on a 100 MiB frame of brackets. The result
  is the same; `tests/test_chat_json_depth.py` checks it against the old count on random and
  adversarial text. The 100 MiB frame limit is the one Effect's `ws` WebSocket has by default.

### Docs

- The Teams docs say that the key set is refetched for an unknown key at most once every 30
  seconds, as in Effect's `Jwks`, so a token signed with a key Microsoft added within 30 seconds of
  the last fetch is refused with 403 until those 30 seconds pass.

## 0.6.30 (2026-11-24)

### Added

- `slack_chat.layer` takes `base_url`, passed to its `slack_web_api.layer` (default
  `https://slack.com/api`), so a GovSlack app can use `https://slack-gov.com/api`. Effect's
  `SlackChat.layer` has no such option; its `SlackWebApi.layer` takes `baseUrl`, which
  `slack_web_api.layer(base_url=...)` already matched. Docs: [Slack](https://pyfect.dev/docs/chat-slack).

### Fixed

- CSV decoding with `headers=True` reads an empty cell of an optional field of an `S.Class`, or of
  a union of classes, as a missing key, as it already did for structs (Effect #10759). Classes
  also count as structs when HttpApi finds the names of path parameters, documents the file
  fields of a multipart payload as binary in OpenAPI, and refuses the reserved event name in a
  `StreamSse` events schema: each walk now reads a class's fields through
  `schema.ast.encoded_objects`.
- The SQL event log storages (`make_storage`, `layer_storage`, `layer_storage_subtle`) refuse a
  `poll_interval` of zero, a negative one or infinity when called, raising
  `IllegalArgumentError` (a `ValueError`) that names the value, instead of dying when the layer
  is built.
- Free-threaded CPython: threads asking for the same lazily made value at once all get one
  value. Two threads could each make their own handler tag for an RPC, so a server built on
  one thread found no handler registered from another (`Unknown request tag`); the same race
  hit tool handler tags, middleware client tags, fixed-offset and ICU-only zones from
  `date_time.zone_named` (which then compared unequal), and a TypedDict's derived struct
  (which could raise `KeyError`). Entities held by cluster runners on several threads at
  once are released correctly.
- `mcp_server.register_toolkit` and `mcp_server.toolkit` accept a `content` list built before
  the call (`mappers = [mcp_server.tool_content(...)]; content=mappers`), not only one
  written inline: `ToolContent` is covariant in the tool's name. A mapper for a tool outside
  the toolkit now adds that tool's `Handlers` to the requirements, which the toolkit's
  handlers layer cannot provide, instead of failing at the call.
- `protobuf.message.encode`, `get_extension` and `set_extension` accept a message `decode`
  or `set_extension` returned (`Message`, unknown fields included) as well as a mapping of
  field names, so a decode, edit, encode round trip type-checks without an ignore.

### Docs

- Slack docs, "Slow slash commands": a checked example of a command handler that races its
  work against a 2 second budget, answers `defer` when the budget runs out, and sends the
  answer with `Chat.follow_up` from fibers forked into the interactions layer's scope.

## 0.6.29 (2026-11-24)

### Added

- `pyfect.chat.discord` (Effect's `@effect/chat-discord`, Effect #10581): the Discord adapter
  for `pyfect.chat` over Discord's REST API with no SDK (`discord_rest`), one Gateway shard over
  `pyfect.socket` (`discord_gateway`, which needs the `websockets` extra) that resumes from a
  `ShardStateStore` and replays an event a `DispatchHook` refused, the HTTP interactions
  endpoint (Ed25519 signatures checked through `Signature`, which needs the `crypto` extra, a
  five minute timestamp window, a body limit, typed parsing at the route), buttons, selects,
  modals and slash commands, `with_post_options` to choose who a post notifies, and the pure
  `normalize` and `normalize_interaction`. Docs: [Discord](https://pyfect.dev/docs/chat-discord).
- `pyfect.chat.teams` (Effect's `@effect/chat-teams`, Effect #10581 with #10758): the
  Microsoft Teams adapter for `pyfect.chat` over the Bot Framework Connector with no SDK, and
  the messaging endpoint, which checks each Bot Framework token (RS256 only, a key endorsed
  for `msteams` from the OpenID metadata's key set, issuer, audience, expiry with five
  minutes of skew, and the token's `serviceurl`, channel and tenant) and bounds the body.
  Buttons, dialogs, agent commands, `start_thread` and downloads wait behind `Unverified`.
  Locating mentions in an activity stops after scanning 64 times the text's length, so an
  activity with many mention entities missing from its text costs linear time. Docs:
  [Microsoft Teams](https://pyfect.dev/docs/chat-teams).
- `pyfect.chat.telegram` (Effect's `@effect/chat-telegram`, Effect #10581): the Telegram Bot
  API adapter for `pyfect.chat` with no SDK. The webhook compares the secret-token header in
  constant time before reading the body, with a body limit and a 64 level nesting cap, and
  `layer_polling` runs `getUpdates`, confirming each update only after it ran. Markdown is
  escaped into rich messages that hold no raw HTML, image or non-web link, in linear time;
  entity offsets are UTF-16 units; files, buttons and commands sit behind `unverified_*`
  options; and `normalize`, `normalize_interaction` and `delivery_key` serve a consumer's own
  transport. Docs: [Telegram](https://pyfect.dev/docs/chat-telegram).
- `pyfect.chat.whatsapp` (Effect's `@effect/chat-whatsapp`, Effect #10581): the WhatsApp
  Cloud API adapter for `pyfect.chat` over the Graph API with no SDK. The webhook answers
  Meta's subscription check (verify token compared in constant time) and checks
  `X-Hub-Signature-256` through `Mac`, with a body limit and a 64 level nesting cap. Markdown
  renders to WhatsApp's formatting without ever growing the text, in linear time; replies
  use reply buttons, link buttons and lists; `send_template` writes outside the 24 hour
  window; and `normalize`, `delivery_key` and `update_key` serve a consumer's own transport.
  Docs: [WhatsApp](https://pyfect.dev/docs/chat-whatsapp).
- `jwks.make_remote` and `jwks.layer_remote` take `filter`, which keeps or drops each raw
  key before it is decoded; `max_keys` counts the keys before filtering (Effect #10581).

## 0.6.28 (2026-11-24)

0.6.27 was tagged but never published: a flaky test failed in its release run. 0.6.28 carries its changes.

### Added

- `testing.count_scheduler_rounds()`: a `MixedScheduler` that counts the rounds it runs, for
  tests that check an answer needs no extra round (pyfect-only: Effect has no round counter).
  `MixedScheduler.set_immediate` is public, as Effect's `setImmediate` is, so a test can wrap
  the default instead of importing `pyfect.scheduler._run_soon`.
- `mcp_server.toolkit` and `register_toolkit` take `content=[mcp_server.tool_content(tool,
  mapper)]`, so a tool can answer with MCP content blocks such as images or resources
  instead of JSON text. The mapper gets the tool's decoded success; a mapped tool lists no
  output schema and sends no `structuredContent`, and its failures skip the mapper. Tools
  without a mapper send what they did before (Effect #10733).
- `pyfect.protobuf`, Effect's `effect/protobuf` in pure Python (Effect #10554, #9454): the
  wire `reader` and `writer`; `descriptor.make` and `descriptor.from_file_descriptor_set`,
  which resolve `protoc`'s descriptors (proto2, proto3 and editions 2023 to 2026); and
  `message.encode`, `decode`, `get_extension` and `set_extension` for messages as dicts,
  with unknown fields kept. `descriptor_proto` has the types and descriptors of
  `google/protobuf/descriptor.proto`. Decoding bounds nesting (`max_depth`, 100 by default)
  and varint lengths, and takes an optional `max_size`. The OTLP protobuf exporter now
  writes with `writer.ProtobufWriter`, and log record trace and span ids may be bytes.
- `pyfect.workers.shared_memory` (Effect's `SharedMemory`, Effect #10644): `make(kind, length)`
  allocates a zero-filled `SharedArray` in a `multiprocessing.shared_memory` segment that the
  scope frees when it closes, and `schema(kind)` is the worker message field that carries it.
  Thread and process workers both write into the sender's memory: a process worker maps the
  segment by name rather than getting a copy.
- `pyfect.chat` (Effect's `effect/chat`, Effect #10581 with #10748 and #10750): the `Chat`
  service that posts, edits, reacts and streams to any registered platform adapter, typed
  `ChatError` reasons with a fixed retry value, `chat_markdown.post` and `stream` (Markdown
  split to a platform's limits at block boundaries, code fences closed and reopened, native
  streaming or post-then-edit, failures that say what was posted), typed buttons, selects,
  modals and slash commands with a 3 second deadline (`chat_interaction`), the `ChatHandler`
  event layer, and `chat_test`: an in-memory platform plus the conformance suite adapters
  run. Docs: [Chat](https://pyfect.dev/docs/chat).
- `pyfect.chat.slack` (Effect's `@effect/chat-slack`, Effect #10581 with #10749): the Slack
  adapter for `pyfect.chat` over the Web API with no SDK, the Events API and Interactivity
  routes (`v0` signatures checked in constant time through `Mac`, a five minute timestamp
  window, a body limit, typed parsing at the route), slash commands and modals, native
  streaming with Slack's stop button, `with_post_options` to choose who a post notifies, and
  the pure `normalize` and `normalize_interaction`. Docs: [Slack](https://pyfect.dev/docs/chat-slack).

### Fixed

- `S.to_codec_array_from_single` reaches into schema classes (`S.Class`, `S.Error`,
  `S.TaggedClass`, `S.TaggedError`) and declarations' type parameters, as Effect 4.1.4's does:
  a form-urlencoded body or query string whose array field arrives as one key (`missing=amount`)
  now decodes into a class too. A derived `HttpApiClient` reports a declared `S.TaggedError`
  with such a field as that error instead of an `HttpClientError`. The walk now runs on the
  same derivation as `to_codec_string_tree` and `to_codec_json`, which already covered every
  kind of schema.
- `IllegalArgumentError`, `NoSuchElementException` and `ExceededCapacityError` have the optional
  `message` Effect's built-in errors take: `IllegalArgumentError("bad arg").message == "bad arg"`,
  and `None` when made without one. Code reading `error.message` on a `skill.from_files` failure,
  say, no longer raises `AttributeError`. `TimeoutException` has a `message` too: by default the
  text Effect's `timeout` writes, `"Operation timed out after '10ms'"`, which is also its string
  form as before. Constructors, equality and string forms are unchanged.
- `csv.decode_schema`, `decode_schema_string`, `encode_schema` and `encode_schema_string` accept
  schema classes (`S.Class`, `S.Error`, `S.TaggedClass`, `S.TaggedError`) and unions of them,
  as Effect 4.1.4's `Csv` does, instead of raising "Csv: cannot verify string cells for Class".
  The structured-output codecs (`to_codec_openai`, `to_codec_anthropic`) also rewrite a class's
  fields now (a tuple field is sent as an object, as in a struct), so a class with such a field
  decodes from the model's output. Walks over a schema's encoded side read a class as its
  fields' struct through the new `schema.ast.encoded_structure`, as Effect's `toEncoded` gives it.
- A schema class field whose default is `None` but whose schema refuses `None`
  (`S.field(S.Int, default=None)`) says what it needs when building or encoding the class
  fails on that `None`: "Expected number, and the default None is not one: write
  S.NullOr(schema) for a field that may be None, or S.Union(schema, S.Undefined) to leave the
  key out while it is None". It said only "Expected number".
- Event log SQL servers sharing one database: `EventLog.synced` through one server never
  finished once another server on the database had taken a write. The server reported that
  write as its latest sequence but streamed only the writes it took itself. Both
  `sql_event_log_server_encrypted` and `sql_event_log_server_unencrypted` now stream from the
  table they report from. A server's own writes still reach its clients at once, and other
  servers' writes arrive within `poll_interval` (a new `layer_storage` option, default
  `"1 second"`, positive and finite). Effect's servers stream only their own writes.
- `crypto.password` turns a password into bytes as Effect's `Password` does (`TextEncoder`): a
  lone surrogate (a JSON `"\ud800"` decodes to one) is U+FFFD. It was written as the
  surrogate's own three bytes, so a hash Effect made for such a password never verified in
  pyfect, and pyfect's never verified in Effect. Hashes of such passwords made by earlier
  pyfect versions no longer verify; every other password hashes as before. The URL username
  and password setters percent-encode a lone surrogate as `%EF%BF%BD` too, as the URL Standard
  does and as parsing a URL already did.
- `Redis.reserve`: a reserved connection held in a scope that outlives the `Redis` service (or the `redis_py` layer) no longer deadlocks its shutdown. The pool waited for the connection to come back, which happened only when that scope closed, after the service's. Closing the service now closes the connection, and a later command on it fails with a `RedisError`.
- `SqlClient.reserve`: a reserved connection held in a scope that outlives the client (or its
  layer) no longer deadlocks the client's shutdown on PostgreSQL, MySQL and SQL Server. The pool
  waited for the connection to come back, which happened only when that scope closed, after the
  client's. Closing the client now closes the connection, and a later statement on it fails with
  the driver's `SqlError`.

### Performance

- `pyfect.ai`: a tool call no longer derives the codecs of its failures again on every call. A tool's failed-result schema, a toolkit's (and a tool ledger's) call failures and `durable`'s record of a call are now one schema per tool, whose codecs are derived once; a durable agent with a tool ledger spent about 2 ms per call deriving them.
- Percent-encoding a URL or a form body (`http_request.body_url_params`, `url_params`, URL
  setters) runs in two passes in C instead of a loop per character: a 40,000 character Slack
  message body encodes about three times faster.

### Docs

- Atoms: a query's `stale_time` is measured with the wall clock, not the `TestClock`, as in
  Effect.
- Event log docs, "One remote id per database": the statements that delete extra remote ids
  name the default `effect_remote_id` table, so the page now tells you to swap in your own
  `remote_id_table`. It also says what clients of each server see when several servers share
  one database.
- The 0.6.26 note about MCP HTTP rounds applies to tools registered directly (a `ToolEntry`):
  on `mcp_server.layer_http_request_scoped`, a waiting `tools/call` of such a tool is answered
  with no scheduler rounds first. Toolkit tools (`mcp_server.register_toolkit`) take 2 rounds
  until 0.7.0.
- RPC: over plain HTTP, `remote_parent_span` is always `None`, as in Effect; the caller's span
  travels in the request's trace headers instead. Said in the RPC tracing docs and on
  `TracingEnabled`, `RpcRequest` and `MiddlewareOptions`.
- The Schema guide's Classes section shows a field that may be `None`: a default fills a
  missing key when decoding, but the field's schema must take `None` too, as
  `S.Union(S.Int, S.Undefined)` (no key while `None`) or `S.NullOr(S.Int)` (`null`) do.

## 0.6.26 (2026-11-24)

0.6.24 and 0.6.25 were tagged but never published: flaky tests failed in their release runs. 0.6.26 carries their changes.

### Added

- `pyfect.ai.skill` (Effect's `effect/ai/Skill`): an Agent Skill as a value. `skill.make`
  checks the frontmatter and file paths, `to_files` writes it as a `SKILL.md` and its
  files, and `from_files` reads one back, failing with `IllegalArgumentError`. Its JSON
  codec keeps a file's bytes as `{"base64": ...}`. `mcp_server.skill` and
  `mcp_server.register_skill` take a `Skill` in place of the files.
- `Link` headers (RFC 8288): `headers.Link`, `headers.parse_link`, `headers.format_link`,
  `http.schema.LinkHeaderFromString`, and `response.links` / `response.link(res, rel)`, which
  resolve targets against the response URL and skip anchored links. `Headers.append`,
  `HttpClientRequest.append_header` and `HttpServerResponse.append_header` add to a header
  without replacing it (Effect #10817).
- `redacted_params` on `router.route`, `router.add` and `HttpRouterService.add`, and `params` on
  `http_api.RedactedNames`: the server span and the `middleware.logger` entry record the matched
  path with those params' values replaced by `REDACTED` (Effect #10790).
- `rpc.TracingEnabled`: an RPC annotation choosing which sides make automatic spans
  (`"client"`, `"server"`, `"both"`, the default, or `"none"`), and `remote_parent_span` on
  `RpcRequest` and `MiddlewareOptions`, the span the client sent, to parent a handler's own
  spans. An RPC without a client span still sends its caller's span (Effect #10780).
- AI tool ledger: `ToolLedgerError` is a schema, so a durable workflow can list it in its
  `error=` as it does `ToolOutcomeUnknown`
  (`error=S.Union(tool_ledger.ToolOutcomeUnknown, tool_ledger.ToolLedgerError)`) and a
  failing ledger store reaches the workflow's caller as a typed error. Its `cause` comes back
  as an `ErrorInstance`.
- `ClickhouseClientConfig(disable_initial_ping=True)` skips the `/ping` that `clickhouse.make`
  sends at startup, so the client builds without a server and a statement fails when it can't
  connect. The default still pings (Effect-TS/effect#10782).
- `stale_time` on `atom_rpc` queries (not streaming ones) and on `atom_http_api` `query` and
  `query_of`: the query goes through `atom.swr`, so a hydrated or retained result younger
  than `stale_time` is reused on mount and an older one is revalidated once in the
  background (Effect #9974).
- `cluster_cron.CronSchedule`: a cron job's effective schedule (`cron`,
  `calculate_next_run_from_previous` and `skip_if_older_than` as a `Duration`), provided to
  `execute` and annotated on the job's entity, so code inspecting registered entities can read
  it with `entity.annotations.get_option(cluster_cron.CronSchedule)` (Effect #10754).
- `pyfect.crypto.password` stores passwords as PHC strings: the `Password` service from
  `password.layer(algorithm=...)` hashes with Argon2id or PBKDF2 from `kdf`, verifies against
  the algorithm and salt the stored hash records, and reports with `needs_rehash` when a hash
  no longer matches the configured algorithm. `password.decode` and `password.encode` convert
  between PHC strings and `PasswordHash` values. No new dependency: Argon2id comes from the
  existing `crypto` extra through `native.layer` (Effect #10734).
- `Rational.nth_root(degree)` and `nth_root_unsafe(degree)` (Effect's `Rational.nthRoot` and
  `nthRootUnsafe`): the exact root, `None` (or a `ValueError`) when it is not rational or the
  degree is even and the value negative. The degree must be a positive safe integer
  (Effect #10555).
- `find_my_way.RouterConfig` takes `use_semicolon_delimiter` and `decode_static_path`, and
  `find_my_way.strict_config` turns every path normalization off, so route text without
  parameters matches only as written (`/%73ecret` no longer reaches `/secret`). Pass it as
  `router_config` to `router.serve` or `to_web_handler` when a proxy authorizes by path prefix.
  With `use_semicolon_delimiter=False`, a prefixed router keeps a `;` inside the prefix it
  strips (Effect #10616).
- `case.is_well_formed` and `case.to_well_formed` (Effect's `String.isWellFormed` and
  `String.toWellFormed`): whether a `str` holds no lone surrogate, and the same text with
  each one replaced by U+FFFD, as a UTF-8 encoder would (Effect #10549).
- `testing.warn_lines`, `info_lines`, `debug_lines` and `trace_lines`, and the same
  properties on `TestConsole`: what a test wrote to `console.warn`, `info`, `debug` and
  `trace`, in call order (Effect #10682).
- `xml.decode` and `xml.decode_string` take `namespaces="strict"`, which adds the resolved
  `namespace` and `local_name` to each `StartElement` and `EndElement` and fails with a
  `"Syntax"` `XmlError` on a document that is not namespace-well-formed (an undeclared prefix
  fails with `"Unsupported"` when the document has a DOCTYPE). The declarations of open elements
  count against `max_token_size` (Effect #10635).
- `xml.to_events(element)` turns an `xml.Element` tree, such as one `xml.elements` collected,
  back into events for `xml.encode` and `xml.encode_string`. It walks the tree without
  recursion, so a deep tree cannot overflow the stack (Effect #10687).

### Fixed

- Amazon Bedrock: a conversation whose earlier tool call returned a list, number or boolean
  no longer fails. Such a result was sent as a Converse `json` block, which Bedrock rejects
  for anything but an object; it now goes as its JSON text. Object results are still `json`
  blocks, and a `None` result is still empty text (Effect-TS/effect#10767).
- `csv.decode_schema_string` and `csv.decode_schema` with `headers=True` treat an empty cell
  of an optional key as a missing key for every struct of a union (and behind `S.suspend`),
  using the optional keys of the member the row selects, and before a struct's index
  signatures check the row. Only a plain struct got this before, so a union schema kept `""`
  and failed to decode it as, say, a number. Port of Effect #10759.
- The SQL encrypted event log server works on a PostgreSQL database whose transactions default
  to REPEATABLE READ or SERIALIZABLE (`default_transaction_isolation`). Of two servers starting
  together on a new database, one died with `could not serialize access due to concurrent
  update` while recording the upgrade, and had it got past that, would have stored a second
  remote id: its read after waiting for the other's lock still saw the empty table. Writes to
  one store from two servers failed the same way, as defects. The storage now runs every
  transaction at READ COMMITTED on PostgreSQL, which its locks rely on. MySQL (REPEATABLE READ
  by default) and SQL Server were not affected: their locking reads see the latest rows.
- A SQL encrypted event log server whose remote id table holds several ids (servers that
  started together on a new database under 0.6.22 or earlier, or under Effect, could each
  store one) now always serves the lowest in byte order and logs a warning naming the table
  and how many ids it holds. It served whichever row the database returned first, so servers
  could disagree. Clients that synced under another id sync again once. The event log docs
  show how to delete the extra ids:
  [One remote id per database](https://pyfect.dev/docs/eventlog#one-remote-id-per-database).
- A derived `HttpApiClient` decodes a form-urlencoded response or declared error whose array
  field arrived as a single key (`tags=a`) into a one-element array. It failed with
  `SchemaError: Expected array` before, also under `WithHeaders`; payloads and query strings
  already did this. Port of Effect #10699.
- `mcp_server.register_toolkit` lists a tool annotated `tool.Readonly` and not `Destructive`
  with `destructiveHint: false`. It used to list such a tool as both read-only and destructive.
  A `Destructive` annotation still sets the hint, and a tool that isn't read-only is still
  destructive unless annotated otherwise. The MCP spec reads `destructiveHint` only when
  `readOnlyHint` is false, so clients that follow it see no change (Effect-TS/effect#10752).
- OpenAI `stream_text` keeps the model's refusal explanations. A refused message's
  `text-end` part carries them in `metadata["openai"]["refusal"]`, joined by a blank line when
  there are several, and a prompt built from the streamed parts keeps them in the text part's
  options. Before, a streamed refusal reached the caller as empty text with no explanation;
  `generate_text` already kept it (Effect-TS/effect#10702).
- The PostgreSQL `PersistedQueue` store (`make_store_sql` / `layer_store_sql`) keeps taking
  offers past 2,147,483,647 rows. Migration `0002` widened the `sequence` column to `BIGINT`
  but left its `SERIAL` sequence a 32-bit integer, so offers failed once the sequence reached
  its maximum. A new PostgreSQL-only migration, `0004_widen_sequence`, widens the sequence;
  it runs once when the store starts. Port of Effect #10781, whose migration is `0003`;
  pyfect's `0003` is already `0003_exact_ids`.
- The request URL of a server span's synthesized 5xx error hides the query names an HttpApi
  endpoint's `RedactedNames` declares, as the span's URL attributes already did (Effect #10790).
- `redis_py`: `Redis.subscribe` returns once the server has confirmed `SUBSCRIBE`, as
  Effect's `NodeRedis` does. It returned once redis-py had sent the command, so a message
  published right after it returned could be lost, and an unanswered `SUBSCRIBE` never
  stalled it.
- An RPC client sends no span in its requests when the calling fiber has tracing disabled
  (`TracerEnabled`) or `DisablePropagation` set, as Effect's (Effect #10780).
- An MCP request over HTTP, and an `RpcServer` request over framed HTTP, are answered without
  waiting for scheduler rounds first. An MCP request starts at once, as Effect's `RpcServer`
  starts one, and the end of a response wakes its reader at once. On
  `mcp_server.layer_http_request_scoped`, a `tools/call` whose handler waits took two rounds
  before its answer and now takes none (Effect-TS/effect#10753).
- Atoms seeded with `skip_initial_run`: a hydrated seed that was still waiting runs the
  atom's effect instead of being kept, a runtime that fails to build replaces a waiting seed
  with its failure instead of leaving it waiting, and a refresh before mount while the
  runtime builds keeps the seed shown, waiting. Refreshing one reader of a shared
  serialization key refreshes the node every reader shares (Effect #9974).
- `redis_py`: closing the client cancels the calls still running on its loop before it closes its connections. A subscriber still reading when the client closed reconnected inside redis-py's retry and was left open when the loop stopped (an unclosed `Connection` at garbage collection). The test suite now fails the test that leaves a socket for the garbage collector, and names the transport's owner.
- `rpc.test.make_client(G)` makes a new client each time its effect runs, as Effect's
  `RpcTest.makeClient` does. Every run sent its replies to the first run's client, so a second
  run (another `atom_rpc` registry over the same client, say) waited forever for its answers.

### Docs

- Tool ledger and durable agents: a bare-id ledger record from 0.6.22 or earlier answers every
  later workflow execution that reuses its `tool_call_id`, with the SQL statement that clears
  those rows once no older execution is running; each guarded call in a workflow does one extra
  lookup for it. With `on_unknown="fail"`, `ToolOutcomeUnknown` reaches a workflow's caller only
  when its `error=` schema lists it, and pyright rejects a missing one at `to_layer`.
- `Stream.group_by` and `group_by_key` no longer say a group ends after `idle_time_to_live`
  only when nobody reads it: the time counts from the last value the group took, so a group
  being read still ends when no new value comes. `sse.make_parser`, `sse.decode` and the
  streams guide now say `max_event_size` bounds only the event left unfinished at the end of a
  chunk; a complete event that arrives in one read is accepted at any size.

## 0.6.23 (2026-11-23)

### Added

- `WithHandler.call_failure_schema(name)`: every failure a call of the tool can give its
  caller, as a failed result or an error. `pyfect.ai.durable` stores tool results with it; a
  toolkit wrapping another (as `tool_ledger.guard` does) extends the wrapped one's.
- `tool.ProviderToolConstructor`, the type of a provider-defined tool's constructor:
  `failure_mode` is typed, and `failure_mode="return"` gives a tool whose handler raises
  nothing to its caller. `ProviderDefined`'s `set_failure`, `set_success`, `set_parameters`
  and `add_dependency` return a `ProviderDefined`.

### Deprecated

- `handlers.handle_all({...})`, the mapping form (and with it `builder.HandleAllEntry`, whose
  only use is as a value there): pass `handle_all` `builder.entry(endpoint)(handler)` values,
  which are typed by their endpoint, its own middleware included.

### Fixed

- `durable.layer` with `tool_ledger.guard`: a call whose ledger entry has an intent and no
  result (a crash while its handler ran) gets `ToolOutcomeUnknown` as the ledger's docs say,
  a failed tool result with `on_unknown="tell_model"` and the call's typed failure with
  `"fail"`, and a failing ledger store gives `ToolLedgerError`. Each killed the run with a
  `SchemaError` before, on the first run too: the tool activity stored and read back only the
  tool's own failures. It now stores everything the toolkit's `call_failure_schema` covers.
- Encrypted event log servers that start at the same moment on a new SQL database now agree on
  its remote id. Each one used to read the empty remote id table and insert its own id, so the
  servers disagreed about which log they serve. A start that finds no id now locks the upgrade
  record's row, reads again, and inserts only if the table is still empty.
- `Stream.group_by` and `group_by_key` with a finite `idle_time_to_live` no longer lose values.
  A group could expire while a value was on its way into it: with a zero TTL every value was
  dropped, and a group whose reader was slower than its TTL ended early, so the rest of its
  key's values went to a new group. A group now stays open until each offer into it has been
  accepted or cancelled.
- `handlers.handle_all` gives an endpoint with middleware of its own the layer type `handle`
  gives it: pass `builder.entry(Users.me)(get_me)` values, and the group layer needs the
  endpoint's middleware and what that middleware needs, not what it provides. A mapping's key
  can't name its endpoint, so the mapping form typed such an endpoint wrong: pyright accepted
  layers that failed at runtime for want of the middleware, and rejected ones that were fine.
  `builder.entry` also checks each handler's request, success and errors against its endpoint,
  and `builder.entry(endpoint, uninterruptible=True)` takes `HandleAllEntry`'s option.
- `race`, `race_first`, `race_all` and `race_all_first` interrupt a racer that settles the race
  during its own first step. Such a racer used to run on after the race was decided (code after
  completing the `Deferred` the winner waited on ran, and the racer ended with its own value),
  and a racer whose fiber settled the race as it was built (a `FiberRuntimeMetrics` hook) still
  ran. Each racer is now registered with the race before it runs.
- `HttpRouter`: an explicit route such as `GET /test` and a wildcard route `GET /test/*` can be
  registered together in either order. `/test` goes to the explicit route and `/test/anything`
  to the wildcard. Before, registering `/test` after `/test/*` died with "Method 'GET' already
  declared for route '/test'", and the other order did too. A wildcard registered alone still
  serves its bare prefix, and two explicit routes for the same path still fail (Effect #10768).
  `find_my_way.Router.on_fallback` registers a route that a later explicit one replaces.
- An RPC socket client's pings keep their rhythm across reconnects, as in Effect. Each
  reconnect restarted the ping interval, so a client's silence verdicts shifted by however long
  its reconnects took. Effect's pinger keeps ticking from when it started, whatever the socket
  does. The interval still restarts at the first open, so a request that times out at twice the
  interval still finds the connection's error on its retry.
- `sse.decode` emits the events it parsed before an event that is too large, then fails with
  `SseError` (`EventTooLarge`). When a complete event and an oversized one came in the same
  chunk, the complete event was dropped.
- `tool_ledger.guard` keys a call made inside a workflow by `<execution id>/<tool_call_id>`,
  so two executions on one database whose model reuses an id no longer answer the second
  one's call from the first one's record. Outside a workflow the key is still the bare id,
  and a record an earlier release stored under the bare id still answers the call.
- Cluster workflows: an activity's result reaches its workflow when the activity's reply is
  redelivered to the same runner. That happens when the runner's shard-ownership check fails
  once while the reply is being saved. Before, the redelivered request found no registration
  and answered `Suspended`, so the workflow waited forever. A redelivered activity now returns
  the result it already produced, without running again, unless it runs `WithTransaction`, in
  which case its transaction rolled back and it runs again. Two attempts of the same activity
  running at once (an `activity.CurrentAttempt` given to each) also get their own results
  instead of hanging. A runner that gives up a request it no longer owns releases its claim
  only after the request's fiber has exited, so the storage poll can't hand the request back
  while the runner would still drop it (Effect #10791).

### Docs

- Durable agents and the tool ledger: state an agent keeps beside the transcript (a list a
  handler appends to) is not rebuilt on replay; outside the workflow on the cluster engine a
  `RequestDiverged` arrives as an `S.ErrorInstance` named after it; with `SuspendOnFailure` a
  caller waits until the run is resumed, so poll or set a timeout.

## 0.6.22 (2026-11-21)

### Added

- `pyfect.ai.durable` makes an agent loop durable without changing its code: provide
  `durable.layer` over the `LanguageModel` a workflow uses, and every model request and tool
  call inside the workflow runs as one of its activities, named by its place in the run
  (`pyfect/ai/<n>/model`, `pyfect/ai/<n>/tool/<i>`), so a crashed run resumes without calling
  the model or a tool again. Each step stores its output and a hash of its request, never the
  prompt, so history grows with the turns and not with the conversation (on SQLite, about 710
  bytes a turn: 7.5 kB at 10 turns, 72 kB at 100). A replay whose request hashes differently, because
  the code changed under a running execution, dies with `RequestDiverged` instead of reusing
  the stored answer. A streamed request is stored once its stream ends and reaches the caller
  as one chunk, on the first run and on replays. Replayed steps spend a budget made in the
  workflow's body again, so a resumed run stops where an uncrashed one does, and tools behind
  the tool ledger never run twice. Other frameworks' durable agents overflowed their history
  (Temporal #1890, terminated at call 53 of 100) or replayed changed requests from stale
  results. `explore.activity_crashes` takes `at=` and `stored=` to split a long sweep into
  parts.

## 0.6.21 (2026-11-21)

0.6.20 was tagged but never published: flaky tests failed in its release run. 0.6.21 carries its changes.

### Added

- `pyfect.ai.budget` caps what a whole agent run spends: input, output and total tokens, model
  requests, tool calls, and cost through a price function. `effect.pipe(budget.limit(limits))`
  gives the run a budget that every `LanguageModel` request and tool call under it draws from,
  forked fibers, parallel tool calls and sub-agents with models of their own included, and a
  nested limit draws from the ones around it too. Each request reserves its worst case (the
  prompt's estimated tokens plus `max_output_tokens`) before it is sent and settles to the
  response's `usage`, giving back the rest; a tool call is counted before its handler runs. A
  call that doesn't fit fails with `BudgetExceeded` before the provider or handler is called,
  and its concurrent siblings are interrupted. In other agent frameworks these limits
  overshoot when calls run in parallel or nest (8 parallel delegations under a limit of 9 tool
  calls made 16). Effect has no counterpart; the AI budgets page shows it.
- `pyfect.testing.explore` runs an effect many ways to find races and crash bugs.
  `explore.schedules(effect, check)` runs it under up to `runs` distinct fiber schedules
  (every one with few deviations from first-come order, then random ones from `seed`), with
  `interrupts=True` an interrupt landing at each step, and raises `ScheduleFailure` naming the
  schedule (`replay=` reruns it), the seed and the interrupt point. `explore.activity_crashes`
  stops a workflow after each activity ran, before and after the engine stored its result,
  resumes it and runs the check ("the payment ran once"), on the memory engine or a cluster
  engine such as `single_runner.layer` on SQLite. It is the engine of `tests/interleave`, which
  no longer patches `Fiber._finish`: it counts fibers through `FiberRuntimeMetrics`.

### Fixed

- `interpreter_pool` with the `PYFECT_WARN_BLOCKING` watchdog no longer corrupts memory on
  Python 3.14 before 3.14.8. There `sys._current_frames()` also made frame objects for the
  pool's subinterpreters, from the wrong interpreter's allocator (python/cpython#158364), and
  the process died with `free(): invalid pointer` or `double free or corruption`. The watchdog
  now skips its sample while a pool's subinterpreter runs code.
- A `Pool` borrower no longer sleeps forever next to a free item. A woken borrower whose run
  was busy kept its place in line; a borrower that came meanwhile queued behind it and slept,
  and when the woken one took its item it left the line without waking it, though another
  item was free. Leaving the line now always wakes the next borrower asleep while an item is
  free. A pool made in a run that had ended hung growing about one time in 250 without the GIL.

## 0.6.19 (2026-11-21)

### Added

- AI: `chat.interrupt_safe(session)` is the same chat with turns that are recorded however
  they end. A `generate_text`, `generate_object` or `stream_text` turn that is interrupted
  or fails adds the prompt, the model's output that arrived, and each tool call it made with
  its result, or with an `execution-interrupted` result when its handler did not finish, so
  the history stays valid for every provider and finished results are kept. A finished turn
  is recorded as Effect's `Chat` records it, and a plain chat is unchanged. `resume(toolkit=...)`
  runs the unfinished calls again and puts their results in place; with a toolkit behind
  `tool_ledger.guard`, a resumed turn runs no tool twice. Other frameworks leave a tool call
  without a result after a cancel (LangGraph #5672, #6726; OpenAI Agents SDK #5642, #1061).

## 0.6.18 (2026-11-21)

### Added

- AI: `tool_ledger.guard(toolkit, on_unknown=...)` records each tool call, by its
  `tool_call_id`, before its handler runs and again with its result, so a replayed call (a
  retried turn, an approved call run again from the history, a process resumed after a crash)
  does not run its handler twice. A call with a recorded result gets that result back; a call
  that started and has no result runs again only for an `Idempotent` or `Readonly` tool, and
  otherwise gets a `ToolOutcomeUnknown`: a failed tool result the model sees
  (`on_unknown="tell_model"`), or a typed error (`"fail"`). The guarantee is at most once, or
  you are told; it is not exactly once. The ledger is the `ToolLedger` service:
  `layer_memory`, or `layer_sql()` on SQLite, PostgreSQL, MySQL or SQL Server. A toolkit not
  passed through `guard` behaves as before. Other frameworks run the tool again in this case
  (PydanticAI #10926: "2 payments").

## 0.6.17 (2026-11-21)

### Added

- `handlers.handle_all({"getUser": get_user, ...})` registers a group's handlers from a mapping
  of endpoint identifiers to handlers, as Effect's `handlers.handleAll` does: in order, with the
  same error for an endpoint handled twice or not in the group, and only the mapping's items
  (never attributes of its class). `builder.HandleAllEntry(f, uninterruptible=True)` is a value
  with `handle`'s option. A key can't carry its endpoint's types, so `builder.handler(endpoint, f)`
  types a value; the layer's requirements are the handlers', less what the group's middleware
  provides.

### Fixed

- Releasing a `redis_py` layer waits until its client's loop thread has closed, with its
  commands cancelled and its connections closed, as the httpx client's release already did.
  The thread used to stop on its own after the layer's scope had closed.
- A SQL call (psycopg, asyncmy, libsql) interrupted before the SQL loop started it no longer
  runs at all. It used to start, be cancelled at its first await, and release anything it had
  opened by then. Every pyfect loop now runs coroutines for fibers in one way
  (`pyfect._loop_bridge`), so each driver gets the same interrupt and release behaviour.

## 0.6.16 (2026-11-20)

### Added

- `pyfect.__version__` is the installed version (`0.6.16`, say), where Python users look first.
  It reads the same value the OTLP exporters report.

### Fixed

- A coroutine run on one of pyfect's loop threads (the httpx client's, Redis's, the sockets',
  SQL's, the ASGI listener's) is kept until it ends even when nothing keeps its future. asyncio
  holds tasks weakly, so a garbage collection could destroy one still waiting ("Task was
  destroyed but it is pending"), closing it half done instead of running it to its end or
  cancelling it at stop: a Redis connection released after an interrupt could be lost that way.
- `socket.from_socket` no longer leaks a file descriptor when the fiber opening it is interrupted
  before the socket loop adopts it. The duplicate the loop watches was made on the fiber, so
  nothing closed it once the adoption was cancelled; the loop now makes it as it adopts. And
  interrupting a socket opening on the loop waits until the loop has stopped it, so the scope's
  finalizers no longer close the caller's socket while the loop is still taking it over.

### Docs

- `examples/http_api.py` says it needs the `httpx` extra (`uv add "pyfect-dev[httpx]"`), and
  uvicorn the `server` extra: run from a fresh project, it failed with
  `ModuleNotFoundError: No module named 'httpx'`. A test keeps every example that imports an
  extra's library naming that extra.
- The subinterpreters page says that without an `if __name__ == "__main__":` guard, everything a
  script does before its run happens again in the subinterpreter (a file written twice), as
  CPython re-runs the script to find the function.

## 0.6.15 (2026-11-20)

### Added

- Schema: order checks for `S.Decimal` that pyright accepts, as `S.BigDecimal` has
  (Effect's `isGreaterThanBigDecimal` and the rest): `S.is_greater_than_decimal`,
  `is_greater_than_or_equal_to_decimal`, `is_less_than_decimal`,
  `is_less_than_or_equal_to_decimal` and `is_between_decimal` take `decimal.Decimal` bounds and
  compare exactly. The number checks (`S.is_greater_than(0)`) are `Filter[float]`, so pyright
  rejected them on `S.Decimal`. And `S.DecimalFromString` (Effect's `BigDecimalFromString`)
  reads a `Decimal` from the text JSON writes, so a CLI takes one with
  `Argument.string("amount").with_schema(S.DecimalFromString)`.
- Schema: a schema in a field's `Annotated` metadata is the field's schema, in schema classes
  and in a `Struct` of a TypedDict: `amount: Annotated[int, S.Int.check(S.is_greater_than(0))]`
  rejects `-1`, and `total: Annotated[float, S.FiniteFromString]` decodes text, as a pydantic
  model reads it. It was ignored, so the field had its type's plain schema. The checks beside it
  refine it; with several schemas the last one wins, and `S.field(schema)` still wins over the
  annotation. Pyright cannot see metadata, so `S.field` stays the form it checks.
- `fiber_profiler.profiled(eff)` profiles an effect from inside another one, pairing its
  value with the complete report as `fx.timed` pairs it with a duration:
  `report, value = yield from fiber_profiler.profiled(program)`. It counts every turn of
  `eff`, on its own fiber too, and every other fiber's while it runs, as `profile()` does for a
  block. A profile already running makes it die with `ProfilerBusyError`; a failure or an
  interruption ends the profile and drops the report.
- `fx.all` takes one list, tuple or other iterable of effects (`fx.all([a, b])`, giving a
  `list` of their values in order, as Effect's array input gives an array) or one mapping of
  them (`fx.all({"a": a, "b": b})`, giving a dict under the same keys, as `fx.all_dict`), the
  shapes Effect's `Effect.all` takes. Both keep `concurrency`, `discard` and `mode`; they used
  to fail with `effects[0] must be an Effect, got list`. Writing the effects as arguments,
  `fx.all(a, b)`, still gives a tuple keeping each value's own type.

### Docs

- The SQL page has a section on `pyfect.sql.schema` (`find_all`, `find_one`,
  `find_one_option`, `find_non_empty`, `void`), which types a query by schemas: the request
  is encoded and the rows are decoded, so a row of the wrong shape fails with a `SchemaError`.
- The Effects page's table of run functions says which error type each takes and what
  happens to a failure: `run_blocking`, `run_sync` and `run_async` need it to be `Never`,
  `run_main` logs it and exits nonzero, and the `_exit` variants return it as an `Exit`. The
  RPC and SQL pages link to it.
- The RPC page shows a stream handler that reads a service
  (`stream.service(Store).flat_map(...)`), and points to `pyfect.rpc.test.make_client` as the
  way to try a group without a server.
- The generated OpenRouter client's docstrings link to OpenRouter's docs: 45 operations said
  "[Management key](/docs/guides/overview/auth/management-api-keys) required", copied from
  OpenRouter's OpenAPI spec, and their API reference pages linked to that path on pyfect.dev,
  a 404. `scripts/gen_ai_schemas.py` now makes a spec's links to a path absolute on the
  provider's docs site and fails on any other relative link; `tests/test_docstring_links.py`
  fails on a docstring link that isn't an absolute URL, and the site's link check now covers
  the API reference's docstrings as well as the guides.
- Fixes from a newcomer's read of the guides. The HTTP server page no longer says a WebSocket
  write after the reader's scope closes waits forever (since Effect #10730 it fails with the
  reader's `SocketError`), counts its three rules right, and explains
  `from_web_socket(..., disable_reconnects=True)`. The SQL page says `migrator.run` and
  `migrator.layer` come from each driver's migrator (`pyfect.sql.sqlite.migrator`,
  `pyfect.sql.pg.migrator`, ...), not `pyfect.sql.migrator`. The Testing page says to install
  pytest. The Services page says what a tag's `key=` is for, the Resources page explains its
  "Without a scope" example, and the Effects page's run table names the functions the `_exit`
  variants mirror.
- The AI page has a section on OpenAI-compatible APIs with two things to know about
  Cloudflare Workers AI's endpoint, both as in Effect 4.1.4. It streams a digit as a JSON
  number (`"delta":{"content":1}`), and that chunk fails the chunk schema and is skipped, so
  digits drop out of streamed text without an error: prompt for words, or don't stream. A
  retired model answers HTTP 410 with Cloudflare's `{"errors":[{"message":...,"code":5028}]}`
  body, so the error reads "Unknown error" and the reason is in `reason.http["body"]`.

### Fixed

- `interpreter_pool.call` and `try_call` on a function that reads globals of the script you ran,
  in a script without an `if __name__ == "__main__":` guard, hung forever with no output. CPython
  finds such a function by re-running the script inside the subinterpreter (as
  `<fake __main__>`), and the script's own `fx.run_blocking` ran the whole program again in
  there. A pyfect run started during that re-run now dies at once, and the call dies with the
  new `interpreter_pool.MainScriptRerunError`, which says to add the guard or move the function
  into an importable module. The Subinterpreters guide said functions of `__main__` and lambdas
  can't cross; it now says what does: a function or lambda reading no globals crosses as its
  code, other functions by reference.


- Schema: `S.NumberFromString`, `S.FiniteFromString` and the number leaves of
  `S.to_codec_string_tree` encoded a negative zero as `"0"`, so it decoded back as positive
  zero. They now write `"-0"`, and the string tree decodes `"-0"` to `-0.0` instead of the
  integer `0` (Effect #10721).


- AI / OpenRouter: a tool result whose `model_output` holds a file sent the file as a
  `[image/png omitted]` placeholder. It is now sent as content items in order (text, then
  `image_url`, `file` or `input_audio`), empty text dropped and the cache breakpoint on the
  last item; output with only text is still sent as joined text (Effect #10741).


- AI / Amazon Bedrock: a tool result's `model_output` was ignored, so Bedrock got the
  application-only `result` instead of what the tool chose to show the model. It now sends the
  model output as text (empty text for an empty one) (Effect #10703).


- DateTime: a zoneless date string whose hyphens looked like an offset, such as
  `"2024-1-15"`, was read in the machine's local time zone by `S.DateTimeUtcFromString`,
  `make_zoned_from_string` and the other string inputs, instead of as UTC. A zone is now
  only an offset sign, a zone word on its own or a bracketed zone after the first digit,
  with comments removed; an ECMAScript date-only string is read as UTC as before
  (Effect #10690).


- HTTP router: `router.serve(app)` built the server without the app's services, so a request
  handler read a `Reference` the app layer sets (or anything else the app provides the server
  layer) at its default, and a layer the handler provides was built again instead of shared
  through the app's memo map. The server is now built on top of the app's context, as
  Effect's `HttpRouter.serve` does (Effect #10668).


- Socket: a write on a connection a server accepted (TCP, TLS, Unix, the WebSocket server,
  an ASGI WebSocket) made after the handler's reader scope closed waited forever for a reader
  that could never connect again. It now fails with the reader's `SocketError`, and so does
  a later reader. `from_web_socket` and `from_connection` take `disable_reconnects=True` for
  such a single connection; by default writes still wait for the next reader (Effect #10730).
- Queue: the take that drains an ended queue no longer loses its item. It woke the queue's
  `await_done` waiters and takers in the same step, so one of them could interrupt the taking
  fiber before the item reached it, and the item was gone from the queue too. Those wakes now
  run in a task after the take (Effect #10737).
- Cluster workflows: a durable clock or deferred waking a workflow while its run was still
  active (one branch sleeping, another in an activity) closed the execution's scope. Its
  `workflow.add_finalizer` finalizers ran early, the replay that should have continued never
  started, and a later interrupt found nothing left to finalize. The wake now interrupts only
  the workflow body, so the run reports `Suspended` and is replayed (Effect #10695).
- Socket: `from_web_socket` with a `high_water_mark` on a WebSocket without pause counted an
  empty frame as zero bytes, kept buffering frames after the limit was exceeded and left the
  connection open. Each frame now counts at least one byte, frames after the overflow are
  discarded, and the WebSocket is closed with code 1008 (or without a code where the
  transport rejects 1008) (Effect #10628).
- Schema: encoding a string with an unpaired surrogate through `S.StringFromBase64`,
  `S.StringFromBase64Url` and `S.StringFromHex` silently wrote U+FFFD, and through
  `S.StringFromUriComponent` raised (a defect). The encoding getters now fail with an
  `InvalidValue`, "Expected a well-formed Unicode string" (Effect #10725).
- MCP server: registering a toolkit scanned the registration context once per tool and copied
  it once per handler, so registration time grew with the square of the tool count. Each
  context is now prepared once (Effect #10751).
- HTTP API docs: `scalar.layer` bundled Scalar 1.43.5, whose request examples add an
  undeclared `Accept: */*` header and which ignores `customFetch`. It now bundles Scalar
  1.81.0 (pinned by SHA-256 in `scripts/package_scalar.py`, with Scalar's MIT notice), gives a
  document without servers the implicit root server `/`, and takes
  `agent: {"disabled": True}` to hide Ask AI (Effect #10727).
- OTLP: when a failed export disables an exporter for 60 seconds, the message is now logged
  as a warning, not at debug level, where the default log level hid it (Effect #10729).
- `interpreter_pool`: a subinterpreter could be ended under its worker by any other thread that
  listed it (`concurrent.interpreters.list_all()`, as a test or a leak check does).
  `concurrent.interpreters.create()` ends an interpreter when the references its shared
  `Interpreter` objects hold drop to zero, and a listing made while a worker was starting could
  leave the worker holding no reference: when the listing's copy was dropped, CPython ended the
  interpreter, so the next call and releasing the layer hung forever (on the free-threaded build
  it could also crash the process). The pool now makes its interpreters without that count and
  ends each only with its own `close()`. A worker that fails in itself (its interpreter will not
  close, because something else closed it) no longer dies silently: a call it was running fails
  with the error, and releasing the layer dies with it instead of waiting forever.
- `fiber_profiler.profile()` no longer raises `RuntimeError: dictionary changed size during
  iteration` when its block ends while other threads run fibers. Ending a profile cannot wait
  for a turn another thread is still counting, so each thread's totals now stop changing
  before they are merged; a turn still running when the block ends is not counted.
- `fx.managed` and `CloseableScope` blocks: when the block raises and a finalizer fails, the
  note added to the block's exception holds only the failed finalizers, as documented, under
  `Failed finalizers:`. It held the scope's whole cause, so it repeated the block's own error,
  once more through each finalizer error's context (they run while it is being handled), and
  an uncaught error printed the block's traceback three times. The exception and the scope's
  cause are unchanged.
- The SQL encrypted event log server storage could fail to start on SQL Server with "There is
  already an object named '<prefix>_remote_id'" when another instance opened the same database
  at the same moment: both found the remote id table missing and the second create failed. Its
  remote id and session auth bindings tables were the only ones created without the retry every
  other table gets; they now go through it too, and
  `tests/test_table_creation_retries.py` fails on any `CREATE` in the storage that no retry
  covers.
- Running something that is close to an effect says what to write instead (every parameter
  that takes an effect, `fx.run_*` included). An `@fx.fn` function passed uncalled used to get
  "to run a function, pass fx.sync(f) or fx.suspend(f)", which led the wrong way; it now gets
  `greet is an @fx.fn function: call it to get its effect, greet(...)`. A generator function
  says to decorate it with `@fx.gen` (or `@fx.fn` when it takes arguments), a generator object
  says the same of its function, and a `Stream` points to `stream.run_collect()`.
- `.pipe(f, g)` on an effect, a layer, a stream, a schema or anything else with `.pipe` said
  only `pipe() takes 2 positional arguments but 3 were given`. It now says `.pipe` takes one
  function on purpose (pyright loses type narrowing after a multi-step pipe's first step) and
  to chain `.pipe(f).pipe(g)`. pyright still rejects the call.
- `fx.all([a], b)`, a list among other effects, says to pass the effects either as arguments
  or as one list.
- A check in a field's `Annotated` metadata that can't run on the value (`count:
  Annotated[int, S.is_min_length(1)]`, a length check on an int) raised `RuntimeError:
  Constructor adapter can only throw schema issues` when constructing (`Sync adapter can only
  throw schema errors` when decoding), naming neither the field nor the check. It now raises a
  `TypeError` naming both, chained from what the check raised: `Bin.count: the check
  is_min_length (a value with a length of at least 1) raised on 3: TypeError: object of type
  'int' has no len(). Give the field a check that fits its type`. Effect has no schema error
  for a filter that throws, and pyright can't see a check inside `Annotated`. Defining the
  class still succeeds, as a default, a union member or an optional field may never meet the
  check. `S.Struct` over a TypedDict names the key the same way (`Line['quantity']: ...`).
- `S.Struct` over a TypedDict with a key whose annotation has no schema (`at: datetime`) said
  only `No schema for the annotation <class 'datetime.datetime'>: give the field its schema`.
  It now names the struct and the key and shows the fix, as `S.Class` names the field:
  `Event['at']: No schema for the annotation <class 'datetime.datetime'>: give the field its
  schema, S.Struct(Event, at=...)`. A key of a nested TypedDict shows the path
  (`Calendar['first']: Event['at']: ...`).

## 0.6.14 (2026-11-19)

0.6.13 was tagged but never published: its release workflow could not start.

### Added

- Scopes from plain Python code: `fx.managed(eff)` runs a scoped effect (a resource from
  `acquire_release`, or `layer.build()` for a layer's services) on entering a `with` or
  `async with` block, binds its value, and closes its scope when the block ends.
  `CloseableScope` is a context manager too. The block's exit is the scope's: a raise is a
  defect, Ctrl-C or asyncio cancellation an interruption, so finalizers run as `fx.scoped`
  runs them, in reverse order and with the same exit. The block's exception propagates, with
  failed finalizers added as a note; after a clean block they are raised as `run_blocking`
  raises their merged cause. A failed acquire releases what it acquired and is raised.
- Exception groups for causes: `Cause.to_exception_group(message=None)` gives a cause's
  `pretty_errors()` as one `ExceptionGroup` (a `BaseExceptionGroup` when one is not an
  `Exception`), and `run.unwrap_group(exit)` raises it for a cause holding several errors
  (siblings that failed together, failed finalizers), so tracebacks show each one and callers
  can use `except*`. A cause with one error raises exactly what `run.unwrap` raises. Opt-in:
  `unwrap` and the run functions still raise the first error with the full cause as a note.
- anyio support for `run_async` and `run_async_exit`, a `ManagedRuntime`'s too, on anyio's
  asyncio backend (which Starlette and FastAPI use). Leaving a cancelled anyio scope
  (`move_on_after`, `fail_after`, a task group's `cancel_scope`) interrupts the fiber and ends
  once its finalizers have run, as `task.cancel()` does; it used to spin forever, since anyio
  cancels the waiter again at every await and the wait awaited even after the fiber was done.
  `from_async` and `try_async` cancel an anyio coroutine when the fiber is interrupted. Trio is
  not supported (`run_async` raises `RuntimeError("no running event loop")` there).
- Schema: `S.Decimal`, a finite `decimal.Decimal` (Python-only; Effect's decimal stays
  `S.BigDecimal`), and the schema of a `decimal.Decimal` annotation, which had none. JSON
  writes it as its text (`"9.99"`, `"1E+2"`), which reads back to the same digits and exponent;
  the text read is ASCII digits with an optional sign, point and exponent, so `NaN`, spaces and
  underscores, which `decimal.Decimal()` would take, are refused.
- `pyfect.fiber_profiler` (Python-only): `with fiber_profiler.profile() as report:` times every
  fiber turn (a run of a fiber until it waits or yields) on every thread with `sys.monitoring`,
  and reports CPU and wall time per fiber id and per span name as `FiberTime(cpu_ns, wall_ns,
  turns)`, exclusive of fibers resumed inside a turn. It watches only `Fiber._run`'s start and
  return, so the fiber loop is unchanged and nothing is set up while no profile runs.
- `fx.on_thread(eff)` (Python-only): runs `eff` as the root fiber of a run of its own on a new
  thread, with the caller's services, and takes on its value, typed failure or defect.
  Interrupting the caller interrupts it and waits for its finalizers. On free-threaded 3.14t
  CPU-heavy effects under it use several cores (an effect of 100k `fx.sync` steps: 1.6x on 4
  threads, 2.6x on 8; see the new "Parallel effects" guide and `benchmarks/parallel.py`); the
  default single-thread runtime is unchanged.
- `pyfect.interpreter_pool` (Python-only, needs Python 3.14): `interpreter_pool.call(f, *args)`
  and `try_call` run a pure function in one of a pool of subinterpreters
  (`concurrent.interpreters`), each with its own GIL, provided by `interpreter_pool.layer(size)`.
  The result comes back as the effect's value; a raised exception as a defect (`call`) or an
  `UnknownError` / `catch=` failure (`try_call`), as itself when it pickles. Interrupting
  withdraws a queued call and abandons a running one; releasing the layer closes every
  interpreter, so it waits for an abandoned call to return. On the GIL build 8 calls of
  pure-Python work ran 7x as fast as one at a time (`fx.blocking`: 1x); see the new
  "Subinterpreters" guide and `benchmarks/interpreter_pool.py`. On 3.13 the layer dies with
  `InterpretersUnavailableError`.
- Testing: `pyfect.testing.leave_out_host_freezes(source)` leaves the time the host froze the
  whole process for out of every test's timeout, up to the timeout again; `source` returns a
  `HostFreezes(total, settling)`. A timeout that left time out says so: "test timed out after
  5.0 s of running time (7.9 s elapsed; host froze the process 2.9 s, not counted)". Unset,
  timeouts are unchanged. pyfect's own suite sets it from its stall watchdog, which counts a
  freeze only when faulthandler's dump came late, so a C call holding the GIL still counts.
- Cluster: `RunnerStorageService` takes an optional `release_many=` operation, and an
  `EncodedRunnerStorage` driver may add a `release_many` method (`EncodedReleaseMany`); the
  shutdown handoff releases shards in chunks through it (below). A storage without one
  releases a chunk one shard at a time through its current `release`, so existing storages
  keep working unchanged. A custom storage that can release several locks in one write should
  implement it.

- `pyfect.rational`, Effect 4.1.4's `Rational` (#9990, #10465): exact fractions, always in
  lowest terms with a positive denominator (the class refuses any other pair; `make` /
  `make_unsafe` reduce), with Effect's arithmetic, `pow`, comparisons, `from_number` (the
  float's exact value), `from_big_decimal`, `from_string` / `format` (`"numerator/denominator"`),
  `to_number_unsafe` (the ratio rounded once) and `to_big_decimal(scale=, mode=)` with
  `BigDecimal`'s rounding modes. `S.Rational` (written in JSON as its text),
  `S.RationalFromString` and `representation.rational_reviver` come with it. Like
  `big_decimal.from_string`, `from_string` reads at most `rational.MAX_DIGITS` (30,000)
  significant digits by default, set with `max_digits`, and prints any size.

- `http_api.api.RedactedNames`, Effect 4.1.4's `HttpApi.RedactedNames` (#9995): an annotation on
  an API, group or endpoint naming query parameters and headers whose values are redacted in
  that endpoint's client and server spans, without modelling them as `Redacted`. A string
  query name also covers its bracketed keys (`buildargs[NPM_TOKEN]`), the names of the API,
  group and endpoint add up, and the server applies them before decoding, so a request that
  fails to decode is redacted too. The values sent and decoded are unchanged.

- `http_api.schema.get_encode_to_with_headers_parts`, Effect 4.1.4's
  `getEncodeToWithHeadersParts` (#10537): the declared body and headers schemas of an
  `encode_to_with_headers` schema, also on schemas read through `reflect`.
  `get_response_encoding_schema` is documented as public, as in Effect.

- AG-UI, Effect 4.1.4's `AgUiSchema`, `AgUi` and `AgUiServer` (#9842), as
  `pyfect.ai.ag_ui_schema`, `pyfect.ai.ag_ui` and `pyfect.ai.ag_ui_server`.
  `ag_ui_schema` holds the protocol's run input, messages and events; decoding drops union
  members from newer protocol versions instead of rejecting the run. `ag_ui.to_prompt`
  turns a run's conversation into a `Prompt` (client instructions dropped unless
  `trust_client_instructions=True`), `ag_ui.from_stream_parts` turns response parts into
  events, and `ag_ui.with_run_lifecycle` opens a run, closes what was left open and ends a
  failed run with one `RUN_ERROR`. `ag_ui_server.layer_http(path=, agent=)` (or `run=`)
  serves a run as server-sent events with a 15 second keep-alive, rejecting an invalid
  input with 400 before the stream opens; `ag_ui_server.agent(toolkit=, system=,
  max_steps=)` answers with the current `LanguageModel`, offers the client's tools as
  client-executed tools, lists their calls as `pendingToolCallIds` and gives handlers the
  run through `RunInput`. `endpoint` and `agent_handler` add it to an existing `HttpApi`.
- `chat.Service.stream_text(max_steps=)`, as in Effect 4.1.4 (#9842): up to `max_steps`
  rounds, sending tool results back to the model until a round needs no tools or a call is
  left for the application. The default of 1 keeps one round.
- `tool.make(execution="client")` and `tool.dynamic(execution="client")`, Effect 4.1.4's
  client-executed tools (#9842): a tool the application runs. It needs no handler in
  `to_layer`, `generate_text` and `stream_text` return its calls unresolved, and handling
  one is a defect. `tool.is_client_executed` and `tool.requires_handler` tell them apart.
- `http_api.schema.StreamSse(keep_alive=)`, as in Effect 4.1.4 (#9842): the server writes a
  `: keepalive` comment each time the interval elapses while the event stream is open, so
  proxies keep an idle response open.

- `pyfect.cli.command_spec`, Effect 4.1.4's `CommandSpec` (#10377): `resolve(app, path)` gives
  a command path as data for documentation tools, without running handlers, prompts, `Config`
  or effectful defaults: its flags with their scope (local, inherited, global), type,
  requiredness, fallbacks in the order the parser tries them, variadic bounds and annotations,
  its arguments and its subcommands. `Flag.annotate` / `Argument.annotate` / `param.annotate`
  attach custom metadata to a parameter for it, and `ParamMetadata.is_required` says whether
  parsing fails without the parameter.

- `Command.validate` takes a check that fails with your own errors, as in Effect 4.1.4
  (#10376): such a failure is reported like a handler failure (rendered when it has a user
  message, no help) and its type joins the command's errors. A `CliError` is still shown
  with the help.

- `pyfect.rpc.open_rpc`, Effect 4.1.4's `OpenRpc` (#10173): `from_rpc_group(group, info=...,
  servers=...)` describes a group's RPCs as an OpenRPC 1.3.2 document, with Draft 7 schemas
  (shared definitions under `components.schemas`) of what the JSON-RPC serializer sends: named
  or positional params, the result, errors read from literal `code`/`message` fields, and an
  `x-effect-stream` extension for streaming RPCs. The `Summary`, `Description`, `Tags`,
  `Examples`, `Deprecated`, `ExternalDocs` and `Errors` annotations fill in each method.

- `RpcGroup.annotations`, `annotate` and `annotate_merge` (Effect's group annotations): defaults
  for the group's RPCs, which their own annotations override.

- `cluster.message_retention.make(entity=..., retention=...)`, Effect's
  `MessageRetention.make`: a singleton that deletes a persisted entity's requests whose
  final reply is older than `retention`, every `interval` (one minute), in batches of 1,000,
  and logs a failure and tries again on the next interval. `MessageStorageService` gains
  `delete_processed(entity_type=..., completed_before=..., limit=...)` on the memory, noop and
  SQL storages (every dialect; migration `0006_retention_index` adds its index), as in Effect
  4.1.4 (#10267). A custom `EncodedStorage` or `StorageBase` written before this gets it by
  implementing `message_storage.DeletesProcessed`; until then `delete_processed` fails with a
  `PersistenceError`.

- `pyfect.ai.workload_identity` (Effect 4.1.4's `WorkloadIdentity`, #10512, #10482): an
  `HttpClient` transform that authenticates requests with access tokens exchanged for a
  workload's identity token, cached until shortly before they expire, discarded on a 401,
  never following a redirect of the exchange and keeping the identity token out of every
  error. Provider modules `pyfect.ai.anthropic.workload_identity` (federation rules, with the
  OAuth beta header), `pyfect.ai.openai.workload_identity` (RFC 8693 token exchange; WebSocket
  mode authenticates each connection) and `pyfect.ai.openrouter.workload_identity`, each with
  `make` and `layer`.

- `httpx_client.FollowRedirects`: whether httpx follows redirects for the requests sent under
  it, overriding the client's own `follow_redirects` (Effect's `FetchHttpClient.RequestInit`
  `redirect` option).

- `pyfect.ai.amazon_bedrock`: Amazon Bedrock's Converse API as a provider, as in Effect 4.1.4
  (#9980). `client` signs requests with AWS Signature Version 4 on the `Digest` and `Mac`
  services you provide, or sends a Bedrock API key, or runs a `credentials` effect before each
  request; `layer_config()` reads the `AWS_*` variables. It decodes ConverseStream's
  event-stream framing (CRC-checked) and maps Bedrock's errors to `AiError`.
  `language_model` covers text, tool calls, reasoning (with its signature or redacted content,
  sent back in later turns), images and documents, cache points and structured output (a
  forced tool, or native with `structured_outputs`). Responses keep the fields and events the
  provider does not model. No new dependency.

### Fixed

- Schema: checks in a field's `Annotated` metadata were silently dropped. In a schema class or
  a TypedDict given to `S.Struct`, `on_hand: Annotated[int, S.is_greater_than_or_equal_to(0)]`
  was plain `S.Int`, so `-1` was accepted; the check now runs when constructing and when
  decoding, also under a `type` alias, a `NewType` or inside a container
  (`list[Annotated[int, ...]]`), innermost first. Metadata that is not a check is still
  ignored, and an explicit `S.field(schema)` still wins. A field annotation with no schema
  names the field in its error (`Price.value: No schema for the annotation ...`).
- Scheduler: a timer a run left pending when it returned (a forked fiber's sleep or timeout,
  handed to the background scheduler) stays in the background scheduler's heap until its
  deadline once cancelled, so an interrupted hour-long sleep held its entry for the hour.
  Cancelling it now removes it there too, as for every other timer.
- `TestClock.sleep` takes the steps Effect 4.1.4's takes (Effect-TS/effect#10326): a suspend
  around its acquire, not a generator. Under a tiny `MaxOpsBeforeYield` a fiber starved by
  `adjust` stopped one step earlier than Effect's, outside the sleep's uninterruptible acquire,
  so interrupting it ended it where Effect's waits.
- Schema classes: constructing one with checks on cost twice what it costs with
  `disable_checks` (an `eventlog.Entry` took 3.5 us against 1.9 us). After parsing each
  field, the constructor collected the values and parsed them again as a whole. Each field is
  now parsed once, its checks included, then the class's own checks run, so checks on cost
  about what checks off cost, as in Effect. A construction that fails reports the same issue
  as before.
- HTTP (httpx client): a response dropped while its client shut down is closed before the
  client's loop closes. Its close could start while the connection pool closed, after the
  wait for pending closes, and the loop thread then cancelled it or closed under it ("Task was
  destroyed but it is pending"), leaking the connection. Closes of responses, streamed bodies,
  cancelled connects (httpcore) and aborted web-handler bodies now all go through one helper,
  which every loop thread waits for, also after its executor shuts down; a test bans keeping
  such tasks in a set of one's own.
- `terminal.live(...).size`: the terminal's resize thread ends when the last `size` stream's
  scope closes, as Effect removes its `resize` listener; it kept polling the size every 0.25 s
  for the rest of the process.

- Docs: workflow activities and compensations run at least once, not once as the workflow
  guide, the README and the `activity` and `workflow` docstrings said. A runner that loses a
  workflow's shard (killed, or its shard-lock refresh timing out under load) leaves every
  activity whose result was not stored yet to run again on the next owner, as in Effect. The
  guide now says so and shows an idempotency key; `tests/test_doc_at_least_once.py` keeps the
  old claim out of the docs and docstrings.
- Cluster: activities could rerun after a durable-clock wakeup on SQL storage: a reset
  requeued interrupts the activity had already consumed, so its next run was interrupted.
  The reset now removes those interrupts and keeps any received after the activity's
  reply, as Effect does since Effect-TS/effect#10629 (after 4.1.4).
- RPC: a stdio server (`layer_protocol_stdio`) stopped reading the rest of a chunk after a
  malformed NDJSON line, and dropped the requests that followed it in that chunk. It now
  answers each malformed line with a defect (with NDJSON JSON-RPC, a `-32700` "Parse error"
  with a null id) and goes on serving the lines around it. `make_unsafe` takes
  `on_decode_error`, which the NDJSON formats call with each malformed line instead of
  raising. After a failed decode, an NDJSON parser also forgets a character split across
  frames, so the next frame decodes. This follows Effect-TS/effect#10579 (after 4.1.4). MCP
  stdio already behaved this way and now has Effect's test.
- RPC: on a protocol with acknowledgements (sockets and workers), a stream whose consumer
  had fallen behind blocked every other response on the client's connection, so a call
  made meanwhile never completed. A chunk that waits for buffer space now waits on its own
  fiber, still ahead of the stream's end, as in Effect-TS/effect#10572 (after 4.1.4).
- Reactivity: after a write, a refresh or remount of an `atom.kvs` atom showed the value
  from before the write. It now shows the last value written, in both modes, as in
  Effect-TS/effect#10613 (after 4.1.4).
- AI (OpenAI): in WebSocket mode, an error event whose details had a `null` `code` or
  `type`, or no `message`, was mapped from the whole event instead of its `error` details.
  The details' other fields, such as a usage limit's `resets_at` or `plan_type`, were also
  dropped. The error is now mapped from its details by status and type, and its metadata
  and body keep every field, as in Effect-TS/effect#10645 (after 4.1.4).
- Strings: the word-based case helpers (`case.snake_case`, `camel_case`, `config_case` and
  the others built on `no_case`) treated every letter and digit outside ASCII as a
  separator, so `snake_case("Café")` gave `"caf"`. Words now hold Unicode letters, numbers
  and combining marks, and case boundaries work in any cased script (`camel_case("CaféÜber")`
  is `"caféÜber"`), as in Effect-TS/effect#10638 (after 4.1.4). No normalization is applied.
  `config_case`, which `ConfigProvider.constant_case` uses, now maps `straße` to `STRASSE`.
- Observability: an OTLP exporter with an infinite export interval kept a fiber waiting
  forever for an interval that never ends. It now starts no export loop and exports only on
  a flush, a full batch or shutdown, as in Effect-TS/effect#10556 (after 4.1.4).
- SQL: a migrator run had no span of its own, so with no pending migrations it left no
  trace, and per-migration spans had no common parent. Each `Migrator` run is now wrapped in
  a `Migrator.run` span carrying the table name in `effect.sql.migrator.table`, as in
  Effect-TS/effect#10688 (after 4.1.4).
- A schema whose aliases only reach each other (a JSON Schema `$ref` to itself) took
  seconds to fail, and up to a minute on Python 3.14; so did any deep recursion that ran
  past pyfect's fresh stacks. The `RecursionError` carried about 180 thousand frames (one
  stack's worth for each of the 300 threads the walk moves to), and rendering them, in the
  sync, option and result adapters' note or a printed traceback, took that long. It still
  fails, as in Effect, but its traceback now keeps the 10 outermost and 10 innermost frames,
  with a note counting the rest, so it fails about as fast as the walk reaches its limit.

- Cluster: a runner whose shard lock operations kept failing force-released its shards but
  stayed registered and healthy, because its liveness probe (an empty `refresh`) still
  heartbeat. Its shards then ran nowhere until its lock storage recovered. Once its lock
  operations have failed for `shard_lock_expiration`, the runner now unregisters itself so the
  other runners take its shards over. A probe that works no longer counts as recovery; a lock
  refresh that works again registers it again. This follows Effect's fix
  (Effect-TS/effect#10689); Effect 4.1.4 has the gap.

- Cluster: a persisted `keep_alive(True)` request that storage redelivered (after its claim
  expired) was answered at once. Its stored reply ended the hold early, so after a runner
  restart storage no longer redelivered it and the entity was not reactivated. The entity
  now keeps the held request's id and gives its redelivery no reply; a second
  `keep_alive(True)` is still answered at once (Effect #10709).

- `EventJournal` (`make_memory`): `with_remote_uncommitted` trimmed the remote's pending list
  through the last entry it uploaded, so an older entry imported from another remote while the
  upload ran was dropped and never uploaded. Only the uploaded entries are removed now
  (Effect #10624).

- `fx.tx` spun on the CPU, rerunning its body at once, when the body recovered from
  `tx_retry` (for example `queue.take().exit()` on an empty `TxQueue`): only a body that failed
  with the retry waited for a ref it read to change. The wait is now decided in one place from
  the retry alone, so a body that recovers from it also waits (Effect #10604).

- RPC client over a socket (`make_protocol_socket`): a failed write of a request or an ack
  was a defect, so the call died instead of failing. It now fails with `RpcClientError`
  carrying the socket error's reason, as a lost connection does (Effect #10658).

- `LanguageModel.stream_text` with `disable_tool_call_resolution=True` dropped the results of
  tools approved (or denied) in the prompt, so `Chat.stream_text` did not record them and ran
  an approved tool again on a later turn. They now come first in the stream whether or not
  resolution is on (Effect #10614).

- `HttpServerResponse.set_status`, `remove_header` and the cookie setters (`set_cookie`,
  `expire_cookie`, `remove_cookie`, `merge_cookies` and the rest) reset an explicit
  `content-type` or `content-length` to the body's. They now keep the headers as they are;
  removing a content header still falls back to the body's (Effect #10605).

- `otlp_logger` exported the invalid ids of the no-op span for a log inside a span made with
  tracing off, and the ids of a span annotated with `DisablePropagation`. Log records now carry
  the nearest span that allows propagation, or none (Effect #10609). The OpenTelemetry logger
  (`pyfect.otel.logger`) had the same bug and is fixed the same way.

- `DateTime.make` ignored a zone followed by trailing whitespace or a comment, as in
  `"Tue, 27 Jan 2026 17:14:06 -0500 (EST)"`: it added a `Z` and read the time as UTC. A
  whitespace-separated offset or zone word before whitespace and one comment now counts as
  the zone (Effect #10620).

- `metric.summary` accepted a NaN quantile: its range check `quantile < 0 or quantile > 1`
  is false for NaN. The first update now dies with "Quantile must be between 0 and 1, found:
  NaN", as for any quantile out of range (Effect #10680).

- Cluster: a stopping runner released each of its shards in a storage write of its own, so on
  a slow or remote database shutdown took 50-100 ms per shard. The shutdown handoff now
  releases them 100 at a time, one write each, through the new
  `RunnerStorageService.release_many` (`EncodedReleaseMany.release_many` for drivers). A
  failed chunk is retried as a single release is, and SQL runner storage still releases
  through the reserved lock connection one operation at a time.
- Sockets: a WebSocket, TCP or UDP read that found data which arrived while its fiber was still
  running took it at once, ahead of the tasks queued before it. A stream RPC over a WebSocket,
  whose client acks each chunk on receipt, then kept the server producing: the reader acked
  chunk after chunk while the consumer that had its items waited, so `take(5)` saw the server
  make 7-35 items on Linux, where Effect makes 5 or 6. Such a read now yields once first, as
  each arrival is an event of its own in a browser or Node.

- Cluster: an `AckChunk` or `Interrupt` saved for a request that is no longer stored is
  dropped instead of stored, on the memory and SQL storages, as in Effect 4.1.4 (#10267).
  Writes to a request's replies (`AckChunk`, `clear_replies`) lock its row first, so they
  can't deadlock with `delete_processed`, and a request save whose conflicting row is deleted
  before it is read inserts again rather than report a save that stored nothing.

- `sql_message_storage` on SQL Server: an index of the same name on another table no longer
  stops the migrations creating the lookup indexes of the message tables, as in Effect 4.1.4
  (#10267). Migration `0005_mssql_lookup_indexes` creates any that are missing.

- `openai_compat`: PDFs given as bytes, base64 text or a data URL are sent as Chat Completions
  `file` parts (`{"type": "file", "file": {...}}`), and an uploaded file's id as a `file`
  part too, as in Effect 4.1.4 (#10514). Bytes were sent as their data URL in a text part, and
  base64 text and data URLs were dropped.

- `openai_compat`: responses with `null` for optional fields (`service_tier`, a tool call's
  `id`, `type` and `arguments`, `tool_calls`, an embedding's `object` and `usage`) decode, as
  in Effect 4.1.4 (#10515). A stream's `service_tier: null` no longer drops the tier an
  earlier chunk reported.

- `openai_compat` and `openrouter`: a refusal (`message.refusal`, or streamed
  `delta.refusal`) with a `stop` finish reports `content-filter` and the refusal text in the
  finish part's `metadata`, as in Effect 4.1.4 (#10534, #10432).

- An interrupted libSQL (Hrana over HTTP) query whose request then failed, or an
  interrupted HTTP connect that then failed, printed "... exception in shielded future"
  with a traceback through the loop's exception handler on Python releases whose
  `asyncio.shield` reports a shielded future's later failure (3.14.7 among them), though
  pyfect retrieves it. pyfect no longer uses `asyncio.shield`: it waits through
  `asyncio.wait` and marks an abandoned outcome as seen, so nothing is printed, as in
  Effect.

## 0.6.12 (2026-11-18)

### Fixed

- `hypercorn_server`: after a too-large WebSocket message the server sent the 1009 close and
  closed the connection at once, so a client still sending its message got a reset and could
  miss the close. As Effect's `ws` server does, it now ends its side after the close and reads
  and drops what the client still sends until the client ends too, or until
  the new `websocket_close_timeout` option (`"30 seconds"` by default, `ws`'s `closeTimeout`)
  passes. This applies to HTTP/1.1 in cleartext; over TLS and HTTP/2 the server
  still closes at once.
- `socket.from_socket` and `socket.datagram.from_socket` register their own duplicate of the
  adopted socket, so closing the original early no longer stops other sockets from reading.
  The original still closes with the reader's scope, and the caller may close it at any time.
- MySQL migrator: the `GET_LOCK` that holds a second migrator back was released just before
  the migration transaction committed, so a second migrator could start in between and miss
  what the first wrote after its last DDL statement. The lock is now released only once the
  transaction has committed or rolled back, with no connection beyond the transaction's.
- Cluster SQL runner storage (PostgreSQL, MySQL): a burst of shard releases, such as a runner
  handing shards to runners that just joined, queued on the one reserved lock connection, and
  each release's deadline counted the time it waited. On a busy machine the later ones timed
  out, which replaced the connection and dropped every shard lock the runner kept, and the
  shards then churned until it caught up. Releases now take the connection one at a time and
  wait outside the deadline, as in Effect PR #10686.

### Performance

- `SqlEventLogServerEncrypted`: a write of many batches, and a compaction commit of many
  staged batches, take a few statements instead of one or two per batch. On a remote
  database each statement is a round trip, so a write of 500 batches to SQL Server took
  about 1,000 statements and now takes a handful. What is stored, at which sequences, is
  unchanged.

## 0.6.11 (2026-11-17)

### Fixed

- A WebSocket handler is no longer interrupted when the client closes after the server has
  answered its close; messages already received can still be pulled. As in Effect, a handler
  is interrupted only when the connection is lost while the server's side is still open (a
  client that ends its side without a close is answered as `ws` does, and gets a 1006). A
  graceful shutdown no longer waits for such a handler once its connection has closed.
- On Linux, a socket or live server connection that was written an empty chunk (a response
  with an empty body, `write_all` with an empty chunk) never ended its stream or finished a
  graceful close, and the socket loop woke for it on every turn. Empty chunks are no longer
  handed to asyncio.
- `pyfect.http.abort`: an `AbortSignal` listener that raised stopped `AbortController.abort()`,
  so the listeners after it (a backend closing its connection) never ran (0.6.9 and before).
  With `with_scope` the raise also turned a finished request into a Die when the scope closed.
  A listener that raises is now logged on the `pyfect.http.abort` logger and the rest still
  run. The new `AbortSignal.on_abort` listens as Effect does: as a WHATWG `AbortSignal`
  listener (once per listener, not when removed during the abort), and at once on a signal
  that already fired (Effect's `if (signal.aborted) f() else signal.addEventListener("abort",
  f)`, without a race between the two). pyfect's own backends use it. `add_listener` behaves
  as in 0.6.10.
- `Command.with_subcommands([a, b])`, Effect's one-list form, raised `AttributeError: 'list'
  object has no attribute 'group'`. It now takes the subcommands as one list or one per
  argument, as do `group(name, ...)` and `command.with_global_flags(...)`; any other entry
  raises a `TypeError` naming what the call takes.
- Over workers, the RPC client and server collected transferables only for the initial
  message. As in Effect, each request is now sent with the transferables its payload
  reported, and each reply (stream chunk or exit) with its own. A client or server protocol
  given `send_transferring=` supports them (`supports_transferables`), and its `send` takes the
  values to move as an optional third argument; the other protocols ignore it.
- `S.to_codec_json(transferable.schema(s, f))` wrote `s` in its own JSON form, so an RPC
  worker message carried `S.Bytes` as base64 text while its transfer list held the raw bytes.
  As in Effect, a declaration wrapped by `transferable.schema` now passes through the JSON
  codec as itself, so the message carries the value the transfer list names.
- `key_value_store.layer_file_system`: processes opening a 0.6.5 store together failed with
  `PlatformError` `NotFound` (`FileSystem.stat`) while renaming its files (0.6.6 to 0.6.10):
  one found the file another had just moved. A file moved or removed meanwhile is now taken
  as done. Opening together could also lose a key whose 0.6.5 file was newer than its
  current one: one process removed the current file just after another had moved the
  0.6.5 file there. The 0.6.5 file now replaces the current one in a single rename.
- On MySQL, processes starting together on a new database could use a store's tables before
  their migrations finished: the first `persisted_queue` offer failed with `Unknown column
  'state'` (and the cluster's message and runner tables could be met half-migrated the same
  way). MySQL commits each DDL statement as it runs, so the rows the migrator records up front
  were visible after its first `CREATE TABLE`, and a second migrator returned at once. The
  migrator now holds a `GET_LOCK` on its transaction's session while it runs on MySQL, as
  `LOCK TABLE` already held a second migrator back on PostgreSQL. Effect's migrator has the
  same race on MySQL.
- System DNS lookups share a bounded pool of four threads, as in Effect.
- Hex decoding and several text parsers use constant memory.
- PostgreSQL: closing a session while a statement on it is still running now waits for that
  statement to end (it fails with a connection error) before releasing the connection.
- Closing a file or socket no longer frees its descriptor while operations are still using
  it: a `FileSystem.open` file's reads and writes, the `uvicorn_server` / `hypercorn_server`
  listening socket, a worker process's channel and a UDP socket's sends. Nothing waits: the
  descriptor closes when the last of those operations finishes, and operations started after
  the close fail as closed (a UDP send with `DatagramSocketClosedError`).

### Performance

- `S.to_codec_json`, `S.to_codec_string_tree` and `S.to_codec_iso` derive a schema's codec
  once and return the same codec after that, as Effect memoizes its codec derivations by
  schema node. Code that derives per call no longer pays for it each time, such as
  `ClusterWorkflowEngine.poll`, which derived its workflow's exit codec (about 1 ms) on every
  poll. The memo is held by the schema node, so it does not keep a schema alive.
- The cluster's runner sync loop builds its storage-read timeout and its refresh sleep once,
  not on every round. A zero `TestClock` sleep returns without deadline arithmetic, and a
  won race skips interrupting racers that have already ended. With
  `refresh_assignments_interval=0` (as in Effect's tests) a round makes 84 pyfect calls
  instead of 120, and takes the same 11 ops.
  `tests/test_sharding_round_cost.py` counts the calls so a regression fails a test.

## 0.6.10 (2026-11-16)

### Fixed

- `pyfect-dev[mysql]` 0.6.5 to 0.6.9 failed every MySQL statement with asyncmy 0.2.18, which a
  fresh install resolves (`SqlError(UnknownError(cause=OverflowError("can't convert negative
  value to unsigned int"), ...))`). The driver wrote -1 into asyncmy's `_next_seq_id` to tell
  whether a failed command had been sent, and asyncmy 0.2.18 made that field an unsigned int.
  The driver now watches what the connection writes instead and changes none of asyncmy's
  state. CI also runs each driver's tests at its newest release and its lowest allowed one,
  whatever `uv.lock` pins, on every change to the drivers and daily.
- `migrate_legacy_store(..., taken_from=pair, through_sequence=0)` was accepted (0.6.9) and
  moved every batch, the first ones of the store taking the tables back included, to `pair`'s
  tables. `through_sequence` is now parsed where the call takes it and refused unless it is 1
  or more; a value inside a batch is still refused, so it ends a batch at or after the first.
- A pair opening tables of its own beside the 0.6.5 tables of its name logged its warning
  on every server start, and kept logging it after `migrate_legacy_store` had given those
  tables to a pair (0.6.9). It is now logged once per process, and not at all once the
  operator has given the tables away, with or without `taken_from`. The server's other
  once-only messages about legacy stores are also logged once per process.
- `sql_event_log_server_encrypted` on SQL Server: two servers opening the same store at once
  could stall for up to 5 seconds (0.4.0 to 0.6.9). Each created the store's snapshot table
  index with its own `CREATE INDEX` after checking `sys.indexes`. One server's check then
  deadlocked with the other's `CREATE INDEX`, and SQL Server only breaks such a deadlock after
  up to 5 seconds. Each table's indexes are now part of its `CREATE TABLE`, so a server that
  finds the table never touches its indexes. Effect's `makeStorage` still creates the index
  separately, so it has the same stall. A table whose index an older version never finished
  creating keeps working without that index.
- A `@testing.effect` test whose deadline passed while it could not be interrupted (in a
  finalizer, say), and which then finished, fails with a `TestTimeoutError` saying it finished
  after its timeout, not that it was interrupted.
- `ChildProcessSpawner.spawn`: a child that exited before its spawn returned (`sh -c '...
  & exit 0'`, say) could have its exit handled first, so `stdin` was already destroyed and
  the first write failed with `Premature close`. The exit is now seen only after the spawn
  has handed the child over, as in Effect, which resumes on Node's `spawn` event before the
  `exit` event: a write made right after the spawn goes in first.

## 0.6.9 (2026-11-16)

### Deprecated

- `LegacyStoreNeedsMigration.automatic` (0.6.8): read the new `state` field
  (`"pending"`, `"unconfirmed"`, `"ambiguous"` or `"unbound"`) instead.

### Added

- `PYFECT_WARN_BLOCKING` takes a duration, as pyfect parses one: `"100 millis"`,
  `"0.5 seconds"`. A bare number is still milliseconds (other than `1`).

### Fixed

- `BlockingStepWarning` made an error (`-W "error:a fiber step"`, pytest's
  `filterwarnings = ["error::pyfect.scheduler.BlockingStepWarning"]`) killed the
  `PYFECT_WARN_BLOCKING` watchdog thread with "Exception in thread pyfect-blocking-watchdog"
  (0.6.8): later blocking steps never warned, and the run and the test still passed. The
  watchdog now hands the error to the fiber that ran the step, which fails with it as a
  defect when it ends (so `run_blocking` raises it and the test fails), and goes on watching.
- SQL `PersistedQueue` on MySQL: an offer no longer deadlocks an `"untilExecuted"` re-offer
  of the same id (0.6.6 to 0.6.8). The offer skips a duplicate with `INSERT IGNORE` again, as in Effect, which
  only locks the duplicate's `(id, queue_name)` entry. `ON DUPLICATE KEY UPDATE` also locked
  the row's primary key, the reverse of the order the re-offer's `DELETE` locks them in, so
  the offer that lost the race failed with a `PersistedQueueError` (MySQL error 1213). An
  element longer than its `MEDIUMTEXT` column (16 MiB of UTF-8) now fails the offer before it
  reaches MySQL, as an over-long id or queue name already did, since `INSERT IGNORE` would cut
  it.
- The `BlockingStepWarning` display showed the blocking line twice: once in the message and
  once below it, where Python shows a warning's line. The message now names the blocking frame's
  file, line and function, and the display shows its source once.
- `BareNumberDurationWarning` for a bare `1` said "read as 1 milliseconds" and suggested
  `"1 seconds"`; it now says "1 millisecond" and `"1 second"`.
- `PYFECT_WARN_BLOCKING=1` set a 1 ms threshold, while `PYFECT_WARN_BARE_DURATIONS=1` means
  "on", so copying one setting to the other warned about nearly every step. A bare `1` now fails
  the import with a `ValueError` that asks for the threshold with its unit.
- `sql_event_log_server_encrypted`: automatic migration of 0.6.5 stores could give a store
  to the wrong pair (0.6.7 and 0.6.8). A store written straight through the storage leaves no
  session auth binding, so the server cannot tell it apart from one only another pair of its
  name could have written. The server now migrates no store by itself: each one waits, logged
  once and listed by `legacy_stores`, until the operator runs `migrate_legacy_store`.
  `layer_storage(migrate_legacy_stores="when_server_written")` restores 0.6.8's rule, for
  databases where every 0.6.5 write went through a server.
- `legacy_stores` only reads and works before the upgrade (`LegacyStore.upgrade_recorded`),
  and `migrate_legacy_store` is refused until an upgraded server has started: only the
  server's first start records which keys had authenticated before the upgrade. In 0.6.8
  either call, run while 0.6.5 still served, counted as the upgrade.
- `migrate_legacy_store(..., taken_from=pair)` no longer hands the batches that pair wrote
  after it got the tables to the store taking them back, whose clients could not decrypt
  them. They move to that pair's own tables at the same sequences. Each alias now records
  where the legacy tables ended when it was made; for one 0.6.6 to 0.6.8 made, pass
  `through_sequence=`. A running server follows the change at once, instead of serving the
  old tables until it restarted.
- A store split by a 0.6.5 node writing after the upgrade is reported as `"split"` and logged
  when its key never authenticated too, where the compaction buckets show it.
- A pair opening tables of its own while the 0.6.5 tables of its name hold batches another
  pair has, or may get, logs a warning naming the name.

### Docs

- The installation page and the README say that `uv init --python 3.14+gil` needs uv 0.9.8 or
  later (older uv says "No interpreter found for executable name '3.14+gil'"), and how to
  update it.
- The "A blocking call defeats timeout" callout on the Concurrency page no longer says nothing
  warns: it points at `PYFECT_WARN_BLOCKING`. A misplaced clause on the installation page is
  moved to the sentence it belongs to.
- The Effects page's table of the `TypeError`s for calling or awaiting an effect lists
  `_Callback` (`fx.never`, `fx.callback`) and `_Fork` (`.fork()`, `.fork_daemon()`).
- The event log upgrade guide covers the opt-in migration, never running 0.6.7 or 0.6.8 beside
  a newer version or downgrading to them, taking tables back with `through_sequence`, and
  what the server's warnings mean.

## 0.6.8 (2026-11-16)

### Added

- `PYFECT_WARN_BARE_DURATIONS=error` raises `BareNumberDurationWarning` at the first duration
  given as a bare number (other than 0 or an infinity), so a run fails on one without a warning
  filter. `=1` still only warns.
- The `HttpClientError` of a relative URL sent to `router.in_memory_client` /
  `layer_in_memory_client` carries a note naming the fix the Testing page gives:
  `client.map_request(lambda request: request.prepend_url("http://localhost"))`, or an absolute
  URL. Its message is still Effect's `InvalidUrl error (GET /check)`.
- `PYFECT_WARN_BLOCKING=<ms>` starts a watchdog thread at `import pyfect` that warns with
  `pyfect.scheduler.BlockingStepWarning`, at the blocking line, about a fiber step that runs
  that long without returning (`time.sleep` in an effect, which silently stalls every fiber on
  the thread and the `.timeout` around it). It samples `sys._current_frames()` and finds the
  frame the innermost `Fiber._loop` called, so the fiber loop has no code for it: unset (or
  `0`), no thread starts and a run does no extra work. A value that is not a positive number of
  milliseconds fails the import with a `ValueError` naming the variable.
- `sql_event_log_server_encrypted.migrate_legacy_store` takes `without_binding=True`, for a
  store whose key had no session auth binding before the upgrade (one written straight
  through the storage), with `not_written_by` naming every other key that shares its 0.6.5
  name; and `taken_from=(public_key, store_id)`, to give the tables back to the pair that
  wrote them when an earlier version gave them to another.
- `legacy_stores(store_ids, public_keys=...)` also checks the names of keys that wrote
  straight through the storage. Each `LegacyStore` has `legacy_name`, `binding` (when its
  key authenticated: `"before_upgrade"`, `"after_upgrade"` or `"none"`) and `migrated_by`
  (`"server"`, `"operator"` or `"earlier_version"`). `LegacyStoreNeedsMigration` has
  `automatic`.

### Fixed

- The `TypeError` for a body under `@fx.fn` that returns neither an effect nor a generator
  (an `async def`, say) began `fn('Effect.fn'): `, the internal frame name of an unnamed
  `fx.fn`. It now begins `fn: ` (`fn('name'): ` under `fx.fn("name")`), as the other `fx.fn`
  messages do; a generic body without a return annotation under `fx.fn("name")` names it too.
- The SQL encrypted event log server moves a store written by 0.6.5 or earlier, under a name
  another pair shares, by itself only on the session auth bindings that existed before the
  upgrade. The first start of 0.6.8 or later copies them into
  `<entry_table_prefix>_legacy_bindings`. A binding made after the upgrade neither gives a
  store to its key nor holds it back from the pair whose key had one, and the name's other
  pairs open tables of their own. On a database 0.6.6 or 0.6.7 opened first, the server
  migrates no store by itself: `legacy_stores` lists each as `"unconfirmed"`, and the
  operator runs `migrate_legacy_store`. A store no key had a binding for before the upgrade
  waits for `migrate_legacy_store(..., without_binding=True)`, however its keys authenticate
  later.
- `legacy_stores` lists every pair sharing each name that holds 0.6.5 batches, those with no
  binding included (`"unbound"`), and the migrations 0.6.6 and 0.6.7 made, as
  `migrated_by="earlier_version"`, for the operator to check.
- `redis_py`: a connection `reserve` was opening when the client's scope closed is closed.
  An interrupt that landed after the connection opened on the client's loop, but before the
  pool took it, left it open with nothing to close it.
- A WebSocket socket hears the events its WebSocket dispatched before the socket listened, as
  a browser's listeners attached in the task that made it do. A client whose connection was
  refused, or opened, got messages or closed, before `from_web_socket` attached its listeners
  failed with a `SocketCloseError` 1006 (or lost the messages) instead of a `SocketOpenError`,
  the messages and the close's code. `WsWebSocket` and the ASGI WebSocket keep such events
  until listeners are added and add several at once (`add_event_listeners`).
- `process`: an input stream (`stdin` or an input descriptor) that fails now wins over the
  child's exit status even when the child exits before the spawning fiber yields. The stream
  starts at once, up to its first wait, so no exit is seen before it has run, as under Node.
  Before, a fast child (`true`) could give exit code 0 on a loaded machine.

### Docs

- `eff()` and `await eff` still fail with Python's own `TypeError` naming the effect's internal
  class (`'_Succeed' object is not callable`, `'_Locally' object can't be awaited`): a
  `__call__` or `__await__` would change what `callable()` and `inspect.isawaitable()` say, and
  CPython builds these messages from the class name with no hook to add to them. The Effects
  page's Common mistakes now has a table of every such message for the common constructors and
  combinators (Python 3.13's await wording too), in a table so the site search indexes it.
  `tests/test_effect_misuse_messages.py` calls and awaits each of those effects and fails if
  the page lacks the exact message.
- The Durations section gave `-W error::pyfect.duration.BareNumberDurationWarning`, which
  Python rejects at startup ("Invalid -W option ignored", before pyfect is imported) and then
  runs on with exit 0, as it does for `PYTHONWARNINGS`. It now gives
  `PYFECT_WARN_BARE_DURATIONS=error`, `-W "error:the duration"` and pytest's `filterwarnings`.
  `tests/test_doc_warning_commands.py` runs each documented command on a program that passes a
  bare number and requires it to fail, and fails on any document that names a pyfect category
  in `-W` or `PYTHONWARNINGS`.
- The install commands (Installation page, README) run `uv init --python 3.14+gil`: a plain
  `--python 3.14` let uv pick a free-threaded 3.14t whenever one was installed, so the page's
  claim that it pinned the standard build was wrong. `tests/test_install.py` fails on any
  documented uv command that requests 3.14 or later without `+gil`.
- The Services page links to the HTTP server's "Routes that need services" section, for a
  route that reads a service per request. The Effects page says a plain `@fx.fn` shows in a
  failure's trace as `at Effect.fn`, and that `@fx.fn("name")` names it and adds a span.
- The upgrade guide moved to
  [/docs/eventlog-upgrade](https://pyfect.dev/docs/eventlog-upgrade); the old URL redirects
  there. It now covers stores with no binding, upgrades and rolling upgrades from 0.6.6 and
  0.6.7, downgrades, and stores two identities wrote. `tests/test_doc_urls.py` checks that
  every docs URL the code and the changelog give is still served.

## 0.6.7 (2026-11-15)

### Added

- `sql_event_log_server_encrypted.legacy_stores(store_ids)` lists the stores, among the
  app's store ids and every authenticated key, whose 0.6.5 tables wait for a migration or
  went to another pair, with where each stands.
- An effect's `repr` says it has not run and how to run it (`fx.run_blocking(effect)`, or
  `yield from effect` in an effect generator), instead of
  `<pyfect._primitives._Locally object at 0x...>`. Effects stay neither callable nor
  awaitable: a `__call__` or `__await__` would change what `callable()` and
  `inspect.isawaitable()` say about them.
- `PYFECT_WARN_BARE_DURATIONS=1` makes every duration given as a bare number (other than 0
  or an infinity) warn with `pyfect.duration.BareNumberDurationWarning`, at the caller's line:
  `the duration 2 was read as 2 milliseconds; write "2 seconds" if you meant seconds, or
  "2 millis" to keep milliseconds`. Off by default; `-W
  error::pyfect.duration.BareNumberDurationWarning` (or pytest's `filterwarnings`) makes it an
  error. A bare number is still milliseconds, as in Effect.

### Fixed

- Cancelling a task awaiting `fx.run_async` / `run_async_exit` (or a `ManagedRuntime`'s) a
  second time while the interrupted fiber ran its finalizers ended the await before they
  finished, and the fiber's exit then raised `InvalidStateError` into the loop, which stopped
  the fiber's other exit observers (an `await_exit` elsewhere hung). Every cancel now waits for
  the fiber, as Effect's `runPromiseExit` does with its signal aborted twice. A cancelled
  standard-schema validation raised the same error in the loop. A future's `set_result` /
  `set_exception` is no longer passed as a callback anywhere (`pyfect._futures.settle` skips a
  done future), enforced by `tests/test_future_callbacks.py`.
- `ManagedRuntime.dispose()` called at the same moment from several threads returned, on all
  but one of them, before the layer's resources were released: each saw no disposal yet and
  began one. Exactly one call now begins the disposal and every other waits for it, as in
  Effect.
- A `ManagedRuntime` run started on one thread while another thread disposed the runtime could
  join the runtime's fibers only after the disposal had closed them, so nothing awaited it: its
  work and finalizers ran after the layer's release, with released services, and rarely
  `run_blocking_exit` raised `AttributeError` instead of returning an `Exit`. A run now either
  joins before the disposal begins (the disposal interrupts and awaits it, as Effect closes
  `fiberScope` before `layerScope`) or dies with "ManagedRuntime disposed". The runtime's
  shared state is used only under one lock, enforced by `tests/test_managed_runtime_lock.py`;
  `tests/free_threaded/stress.py` runs both races without the GIL.
- `NaN` is ordered as Effect's `Order.Number` orders it, before every number, wherever Effect
  orders numbers with it: `TxPriorityQueue` keys (also inside a tuple key), histogram
  boundaries, summary samples and quantiles (a `NaN` quantile reads no sample, as Effect's
  `samples[NaN]`), and the number checks `is_less_than`, `is_less_than_or_equal_to`,
  `is_greater_than`, `is_greater_than_or_equal_to` and `is_between`, so `NaN` now passes
  `is_less_than(5)`. These followed Python's `sorted` and operators, which leave `NaN`
  wherever it falls. `make_is_less_than` and the other bound-check makers take Effect's
  `order=`.
- hypercorn over TLS: shutdown is bounded by the graceful timeout.
- `socket.server.make_web_socket`: closing is bounded by the abort grace period, as Effect's.
- `run_main` handles SIGINT and SIGTERM on its event loop (`add_signal_handler`), so a
  signal always wakes it. A signal that arrived on another thread, or just as the loop went
  to wait, used to leave the program hanging. Every way out of `run_main`, including a
  `KeyboardInterrupt` raised by user code and a real SIGINT, now restores the handlers it
  found, where it used to leave the closed loop's SIGINT handler installed.
- Event log servers refuse a public key or store id that is not well-formed Unicode (holds a
  lone surrogate): `Authenticate` fails `Forbidden` and `StoreIdSchema` does not decode it.
  The SQL encrypted server's storage names each store's tables from text that keeps such
  characters apart.
- A fiber waiting on a `Deferred` (or any wait resumed by a wake-up) that resumes with a
  failure no longer runs the wait's canceler first: the canceler runs only for a cause with
  interrupts, as Effect's `asyncFinalizer` does. The extra steps moved where the fiber yields
  under `MaxOpsBeforeYield`, so it logged after a sibling it logs before in Effect.
- `Stream.take`, `take_until`, `take_while` and `take_while_filter` pull past their end in
  three steps, as Effect's `flatMap(suspend(...), ...)` does, and `Stream.zip`, `zip_with` and
  the other streams that pull their sources with `Channel.to_pull_scoped` no longer spend a
  step before building the pull. A fiber running them under `MaxOpsBeforeYield` yields where
  Effect's does, so a forked child or a queue producer runs at the same point.
- A fiber whose effect is done interrupts and awaits its children in a run of its own,
  counting steps from the first again, as Effect's fiber does. Under a small
  `MaxOpsBeforeYield` it no longer yields there, so a child forked without starting is
  interrupted before it runs, as in Effect.
- `Stream.flat_map` with `concurrency` above 1 (and `switch_map`, `Channel.merge_all`) and
  `Stream.buffer` / `Channel.buffer` build as Effect's generators do, step for step: the queue
  and latch are made as steps, the queue's shutdown is added to the scope as Effect's
  `Scope.addFinalizer` adds it, and `buffer` builds its upstream before making its queue.
- `Queue.fail` / `fail_cause` / `end` on a queue with nothing left to take ends it at once
  and queues no task, as Effect's `failCauseUnsafe` does. The stray task sat in the
  dispatcher of the fiber that made the queue, so that fiber's later forks ran ahead of
  tasks other fibers had queued since.
- `provide_service` and the other effects that run with a changed context restore it as
  Effect's `updateContext` does, uninterruptibly, so an interrupt that arrives while the
  fiber is paused there lands one step later, as in Effect. Before, a repeated effect
  interrupted at that point finished a step early.
- `Stream.buffer`, `group_by`, `partition`, `callback` and `Channel.callback_array` hand each
  chunk on in the step that takes it from their queue, as Effect's `Queue.takeAll` does,
  without a further step to convert it.
- `sql_event_log_server_encrypted.migrate_legacy_store` only migrates a pair that
  authenticated: it refuses a public key with no session auth binding, and, when another key
  sharing the store's 0.6.5 name has authenticated too, until the call names those keys in
  the new `not_written_by`. The server now migrates a store by itself, on its first request,
  when its key is the only one sharing the name that has authenticated, so most upgrades from
  0.6.5 need no manual step. A refusal describes the asking store without telling the
  operator to migrate it. See [Upgrading event log stores from
  0.6.5](https://pyfect.dev/docs/eventlog-upgrade-0-6-7).
- A store the SQL encrypted server refused (`LegacyStoreNeedsMigration`) opens on the same
  server once migrated: a store that fails to open is no longer kept for the storage's idle
  time, which each retry renewed. A failed store open of any kind (a dropped connection) is
  retried on the next request too.
- A refused store is no longer hidden: the server logs a warning naming it once, and the
  client gets an `InternalServerError` saying the store waits for the server's operator,
  with its `store_id`, instead of "Decoding failure" or "Persistence failure". A store a
  0.6.5 node wrote after it opened on a newer version is logged as split.
- `S.is_unique` and `S.is_unique_key` refusing more than 64 distinct items of one hash say
  so, as `FrozenSet` and `Map` do, instead of calling them duplicates.
- `big_decimal.from_string` (and `S.BigDecimalFromString`) refuses a run of more than
  `MAX_DIGITS` significant digits before checking that every character is a digit, so an
  over-long run costs one pass over the text instead of two.
- The httpx `HttpClient` raises `httpx.DecodingError` again when a response body fails to
  decode (a corrupt gzip, deflate or brotli body); since 0.6.6 it raised `NameError: name
  'httpx' is not defined` instead. Lint now enables ruff's TC004, which catches a runtime use
  of a name imported only for type checking.
- `date_time.zone_named` and the `DateTime` zone functions resolve `CST6CDT`, `EST5EDT`,
  `MST7MDT` and `PST8PDT` on systems without tzdata-legacy (Ubuntu 26.04, Debian 13), with
  ICU's data, so they give Node's offsets everywhere (before 1967 they keep standard time, unlike
  the `America/*` zones tz 2024b made them links to). `scripts/gen_icu_zones.py` now decides
  which ids carry ICU's data from ICU's and tz's sources, not from the generating machine's tz
  database.
- A `MissingServiceError` raised while handling an HTTP request carries a note that names
  `router.provide_request(layer)` and says `layer.provide` on a routes layer reaches only its
  build, not its requests (as with Effect's `Layer.provide` there). Its message is still
  Effect's `Service not found: <key>`. A newcomer's `Routes.pipe(layer.provide(Stub))` died on
  every request with no pointer to the fix.
- pyright explains an `@fx.fn` on an `async def`, or on a `def` with no `yield`, against
  the generator body: `cannot be assigned to parameter "f" of type "(**P@fn) ->
  Generator[...]"`, where it used to say `parameter "name" of type "str"`. The
  `fn(name: str)` overload now comes first; what type-checks is unchanged.
- A request whose body is not valid JSON is logged as one `RequestParseError` with the JSON
  error's message, at INFO as in Effect, without the JSON error's Python traceback, which ran
  through the `json` module and made each bad request about 30 log lines.
- `run_main` called where an asyncio loop is already running (in a coroutine, or a Jupyter
  cell) raises a `RuntimeError` that points to `await fx.run_async(eff)`, before it builds
  anything. It used to fail inside `asyncio.Runner` with "Cannot run the event loop while
  another loop is running" and leave two coroutines that were never awaited.
- `help(fx.run_blocking)` and the other run functions show that the result is the effect's
  value (`run_blocking(eff: Effect[A, Never, Any], ...) -> A`, `run_blocking_exit(...) ->
  Exit[A, E]`), where they showed `Effect[Any, Never, Any] -> Any`.
- `fx.yield_now.fork()` and `yield from fx.yield_now` say that `yield_now` is a function to
  call (`fx.yield_now().fork()`), where they raised `'function' object has no attribute
  'fork'` and `'function' object is not iterable`. `yield_now` itself is unchanged.

### Performance

- The stack probe that deep recursive walks (recursive schemas, `Equal`, nested JSON, YAML,
  TOML, logger values, schema binary) make at each level costs the same at any depth: it
  looked `sys.getrecursionlimit()` frames back, so with a raised limit each probe cost as
  much as the stack was deep and a deep walk took quadratic time (a recursive union 8,000
  levels deep at a limit of 100,000: about 920 ms, now about 75 ms, as at the default
  limit). A walk now moves to a fresh stack every 600 or so frames whatever the limit.

### Docs

- ScopedCache: an expired entry keeps its resources until the key is next read, a zero time to
  live keeps the entry (`Cache` keeps nothing), an `invalidate` during a lookup hands its
  waiters a value whose resources are already released, and a `refresh` in flight caches an
  invalidated key again.
- A `Cache` refresh that fails replaces the cached value; an `RcMap` with an idle time to live
  keeps a failed lookup until it expires.
- Pool: a `"creation"` time to live replaces every item, the `min` ones too, and under the test
  clock borrowers forked as the pool grows take their items only after `testing.adjust(0)`.
- Adopting in an asyncio app: what cancelling a `run_async` awaiter does (`CancelledError`,
  after the finalizers), `dispose()` with runs in flight or from several threads, and that a
  run's timeout doesn't cover the layer build it waits for.
- HTTP and TLS: `httpx_client.layer_with(verify=, http2=)`, `socket.make_tls` and
  `TlsUpgradeOptions`, a private CA for `wss://` with `SSL_CERT_FILE`, and that `layer_test`
  with TLS still gives an `http://` client.
- `TxReentrantLock` has no writer preference, and a sole reader can take the write lock.
- [Upgrading event log stores from 0.6.5](https://pyfect.dev/docs/eventlog-upgrade-0-6-7):
  who is affected, stopping every 0.6.5 node first, what the server does by itself, when the
  operator acts, and why stores two identities shared can't be split.
- The docs home said pyfect covers about 64% of Effect v4 while the README and PyPI said
  about 95%. Both now state the number `scripts/parity_summary.py` computes from the weighted
  table in docs/PARITY.md (about 95%, about 94% of the runtime core), and
  `tests/test_parity_summary.py` fails when a page disagrees with the table. PARITY.md opens
  with that one-line summary.
- HTTP server: a "Routes that need services" section: `provide_request`, providing to the
  `serve` or in-memory client layer, why `layer.provide` on the routes layer is not one of
  them, and a test with a stub layer.
- Effects, Common mistakes: using a function's effect as its result, `eff()`, and the
  exact `TypeError` that `await eff` raises, with what to write instead.
- Effects: a "Reading pyright errors" section: a missing service at a run function, the
  long `@testing.effect` error for one, and an `@fx.fn` body that is not a generator.
- Schedules, Durations: how to find every bare-number duration with
  `PYFECT_WARN_BARE_DURATIONS` and fail on them under pytest.
- Testing: the in-memory HTTP client takes absolute URLs (`http://localhost/...`); a relative
  one fails with `InvalidUrlError`, as with Effect's `HttpClient.make`, unlike the
  `layer_test` client, and how to prepend the host.
- Installation: the pip commands make the virtual environment with `python3.13`, since a
  plain `python3` can be older (macOS ships 3.9), and the page shows the "No matching
  distribution found" error pip gives there. The uv commands start with
  `uv init --python 3.14`, which keeps uv off the free-threaded 3.14t, where some libraries
  (`psycopg[binary]`) publish no wheels.
- HTTP server: a table of the failures that answer other than 500 (`RequestParseError` is a
  400, or 413 past `MaxBodySize`), and why `catch_tag(S.SchemaError, ...)` doesn't see a
  body that isn't JSON.
- Effects, Common mistakes: `fx.yield_now` is a function, unlike `fx.void` and `fx.never`.
- Observability: an unnamed `@fx.fn` shows as `at Effect.fn` in a failure's trace, as in
  Effect; `@fx.fn("name")` names it.
- Threads: links `benchmarks/streams.py` and PARITY.md, and says what the dogfood apps it
  cites are.
- Concurrency: a callout that a blocking call such as `time.sleep` holds every fiber, the
  timer of `.timeout` included, and that `fx.blocking` lets the timeout fire.

## 0.6.6 (2026-11-15)

### Added

- `PersistedQueue.offer(..., deduplicate="untilExecuted")`: a custom id stays reserved only
  until its element completes or fails its final attempt; a later offer enqueues it again,
  behind queued work and with its own delay. The default `"untilRemoved"` keeps the id until
  cleanup, as before. On the memory, SQL (every dialect) and Redis stores, as in Effect 4.1.4
  (#10316). A custom store's `offer` gets the option when it takes a `deduplicate` keyword
  (`DeduplicatingOffer`); one written before ignores it, so its offers stay `"untilRemoved"`.
  Redis now parks in-flight and failed ids under finite scores, so cleanup of an old failure
  can't release a newer element of the same id; `+inf` entries left by earlier versions still
  read as in flight.
- Hooks for runtimes and stores outside pyfect, as in Effect 4.1.4 (#7322):
  `entity.KeepAliveHandler`, which `entity.keep_alive` calls instead of messaging the entity
  when a runtime provides it; `persisted_queue.is_dead_letter_cause(cause)`, for a custom
  store's take finalizer to fail an element whose payload can't be decoded at once; and
  `durable_clock.InMemoryThreshold`, the threshold a `sleep` without `in_memory_threshold`
  reads (60 seconds), so an engine whose timers are always durable can provide zero.
- `FlagDescriptor.repeatable` in `cli.completions`, Effect's `repeatable` descriptor field.
- `run.InterruptExitCode`, Effect's `Runtime.InterruptExitCode`: an interruption annotated with
  it ends `run_main` with that code. `default_teardown` gives the largest one when every
  interruption carries one, and 130 otherwise (#10475).
- `http_effect.scope_disable_close` takes the request's `Scope`, as Effect's does, as well as
  its state.
- `language_model.generate_object(..., allow_empty=True)` and `Chat.generate_object(...,
  allow_empty=True)`: the value is an `Option`, `None` for empty or whitespace-only text and
  `Some` of the decoded object otherwise, as in Effect 4.1.4 (#10527).
- Anthropic: `OutputConfig.effort` accepts `"xhigh"` and `"max"`, as in Effect 4.1.4 (#10421).
- `RunBlockingInEventLoopWarning`, a `RuntimeWarning`: `run_blocking` and `run_blocking_exit`
  warn when called on a thread whose asyncio loop is running (in a coroutine or a notebook
  cell), which they block until the effect is done. The effect still runs as before; use
  `await fx.run_async(eff)` there. pyfect's own tests turn the warning into an error.
- `encoding.base64.encode_unpadded`, standard Base64 without the `=` padding, and
  `encoding.base64.decode_lenient`, which reads either Base64 alphabet, padded or not (CR and
  LF ignored, other whitespace rejected), as on Effect main (#10557).
- `encoding.xml.decode` and `decode_string` take `positions=True`, which sets the one-based
  `line` and `column` of each start tag's `<` on its `StartElement`, counted as for
  `XmlError`, as in Effect 4.1.4 (#10406).
- `representation.from_json_schema_document` and `from_json_schema_multi_document` take an
  experimental `close_objects` option: objects with declared properties are closed when every
  object schema they combine omits `additionalProperties` (after `allOf` is merged, so
  inherited properties stay valid), and decoding strips other keys, or rejects them under
  `on_excess_property="error"`, as in Effect 4.1.4 (#10521).

### Fixed

- `mcp_server.layer_http` reads an `initialize` under its own `max_initialize_bytes` limit
  (64 KiB by default; a larger one gets 413), and a session keeps only the decoded
  `initialize` fields, not the whole message.
- A multipart field's `charset` is read as `TextDecoder` reads it, as in Effect: only the
  WHATWG Encoding Standard's labels name a decoder, and any other label decodes as UTF-8,
  instead of selecting any Python codec.
- `hypercorn_server` WebSockets decline `permessage-deflate`, as Effect's `ws` server does,
  take messages up to the same 100 MiB as `uvicorn_server`, and close the connection after a
  too-large message instead of keeping it and its partial message.
- `socket.server.make_web_socket` connections queue at most one incoming frame while no
  handler reads them (websockets' `max_queue=1`; the client too), and the server declines
  `permessage-deflate`, as Effect's `ws` server does. Both can be set through the serve options.
- A multipart body has at most `MaxParts` parts, now 1000 by default (it was unbounded, as in
  Effect); more fail with `TooManyParts`. Provide `MaxParts` to change it, `None` for no limit.
- The router (and MCP resource templates) decode a path's `%25` escapes in one pass, in
  time linear in the path's length.
- An HttpApi path parameter followed by a character the router does not split on
  (`/geo/:lat,:lng`) matches up to that character, in linear time; Effect's lazy `(.*?)`
  could let it take the character too, at polynomial cost.
- `middleware.decompression()` answers 400 to a body with data after the end of its
  compressed stream, as the web `DecompressionStream` Effect decodes with does, instead of
  keeping that data.
- The httpx client decodes a response's `gzip`, `deflate` and `br` codings itself, in pieces
  of at most 64 KiB as the body is read, so `with_body_limit` stops a compressed body before
  it is inflated; httpx inflated each network chunk whole, and stacked codings multiplied it.
- `uvicorn_server` WebSockets decline `permessage-deflate` by default, as Effect's `ws`
  server does (`config={"ws_per_message_deflate": True}` turns it back on).
- An ASGI request's (and WebSocket upgrade's) repeated header lines are joined once, in time
  linear in their number.
- `cookies.parse_header` skips the segments without `=` before the next `=` at once, in time
  linear in the header's length.
- The client cookie jar (`cookies.merge_into_array`, `with_cookies_ref`) refuses from a
  plain-http response a `Secure` cookie, a `__Secure-` or `__Host-` name, and a cookie that
  would replace or shadow a held `Secure` one (RFC 6265bis strict secure cookies), as
  browsers do; Effect's jar takes them.
- `AllowedOrigins`' same-origin check takes the request's scheme: over `https` or `wss` a
  plain-http page of the same host is not the server's own origin, as browsers see it
  (`OriginPolicy.allows` takes an optional `scheme`). An https origin on a plain request
  still is, for servers behind a proxy that ends TLS.
- A UDP socket reads at most 32 datagrams per read callback, as libuv does, so a full
  receive queue no longer holds the network loop the process's other sockets run on.
- OpenAI WebSocket mode counts each response's messages against `max_response_bytes`, as the
  HTTP transport counts a response body: past it the response fails with the same error and
  the connection is replaced.
- RPC server: messages a transport receives before the server runs (while other layers are
  still being built) are replayed one by one, so one that fails ends only itself instead of
  stopping the server for every client. An `Ack` or `Interrupt` without a valid `requestId`
  is answered with a defect for its client (it raised `KeyError` on the server), and an HTTP
  request without an id no longer fails the whole body. Client control messages are read
  through `rpc.message.decode_control`; `tests/test_rpc_server_reads_messages_safely.py`
  keeps the server modules from indexing a client's message.
- RPC over HTTP with a framed serialization (`ndjson`, `schema_binary`): a body that answers more
  requests at once than the stream buffer holds (17 failing requests with the default 16)
  gets its response; the requests are now written while the response is read, where the
  writes used to wait for a reader that only started after them.
- `schema_binary`: a varint read as a number fails past the 147 bytes a finite double needs, and
  long `BigInt`, `Duration` and `BigDecimal` varints are read in near-linear time; both used to
  cost time quadratic in the run's length.
- `schema_binary`: when a schema pass checks the decoded value, the values one frame's
  back-references name are limited to `max_expanded_size` bytes (64 MiB by default, `None` for
  no limit), a new keyword of `to_codec`, `to_codec_direct`, `parser` and
  `rpc.serialization.make_schema_binary`. Past it, decoding fails with a `SchemaError`; a check
  used to run once per reference over the same value.
- Ints a peer sends no longer cost quadratic time when their hashes collide (CPython does not
  seed `int` hashes, so `k * (2**61 - 1)` all hash alike). RPC and MCP request ids, on the
  server and the client, and JSON-RPC batches key them through `pyfect._peer_keys`
  (`PeerKeyDict`, `PeerKeySet`); a JSON-RPC batch item whose id is not a request id no longer
  fails the whole body. `S.FrozenSet`, `S.Map`, `is_unique` and `Array.dedupe`-style dedupes
  refuse values where more than 64 distinct items share one hash (`FrozenSet` and `Map`
  decode to an `InvalidValue`, `is_unique` fails its check, `dedupe` raises `HashFlood`, a
  `ValueError`). `tests/test_peer_hash_keys.py` feeds all-colliding ints to each, and keeps
  maps keyed by `RequestId` from being plain dicts or sets.
- `sql_event_log_server_encrypted`: two (public key, store id) pairs that joined to one
  `publicKey/storeId` string (`("a", "b/c")` and `("a/b", "c")`) shared one store. Upgrading:
  a pair whose `publicKey/storeId` has exactly one `/` keeps its tables and needs nothing. Any
  other pair is keyed apart; if its tables from 0.6.5 or earlier hold batches, which another
  pair may have written, the store does not open (its storage operations die with
  `LegacyStoreNeedsMigration`) until its owner runs
  `sql_event_log_server_encrypted.migrate_legacy_store(public_key, store_id)` once, which
  gives it those tables. Only one pair can claim them (another gets
  `LegacyStoreMigrationError`). Stores whose public keys hold a `/` (base64 keys often do)
  need this before they serve again; a store with no 0.6.5 batches opens as before.
- Event journals (memory and SQL): an imported entry id that is not 16 bytes, or more than a
  day ahead of the clock (one at the UUID v7 ceiling), is no longer the floor of local ids, so
  local writes go on after importing one, also after reopening a SQL journal that holds it.
  They used to fail with `OverflowError` or `IndexError`, as Effect's journals still do.
- `http.headers.parse_http_date` and `parse_retry_after` return an `Err` for a leap second past
  the last `datetime` (`Fri, 31 Dec 9999 23:59:60 GMT`); they raised `OverflowError`, so such a
  `Retry-After` ended `retry_transient` with a defect instead of retrying.
- `HttpClient.with_rate_limiter` no longer learns a `ratelimit-limit` below 1 from a response:
  a request waits `window / limit`, so `0.000000001` parked the key for thousands of years,
  past the hour pyfect allows a peer's time hints.
- Schema: a union of mutually recursive `TypedDict`s (the members met again while their own
  fields are derived are suspended) decodes in time linear in the input's depth. A suspended
  member whose target is made is picked by its discriminator like any other member, where
  every one used to be tried on every value: 2^depth parses under `errors="all"`, the MCP
  server's tool-argument decoding. Issues then name only the members the discriminator picks.
- Process workers: the worker's channel to its parent is no longer inheritable in the worker,
  so a program the worker starts with `additional_fds` (which spawns without `close_fds`) does
  not get it.
- PostgreSQL migrator: a client-key passphrase in `ssl` (libpq's `sslpassword`) reaches
  `pg_dump` through a service file only the user reads (removed after the dump), no longer on
  its command line, which other local accounts can read, or in a failed spawn's error.
- SQL: statements compile in time linear in their segments. The compiler grew the text with
  `+=` on an attribute, copying it for every segment, so an `and_` / `or_` / `csv` over a
  long list took quadratic time; an empty `IN` list now reads only the end of the text.
- Schema: `TemplateLiteral` tries each split point without copying the text on both sides, so
  a long string that does not match (`"-" * n + "a"` against `${string}-${number}`) fails in
  linear time.
- Schema: `format_issue` (the `message` of a `SchemaError`) writes at most
  `issue.DEFAULT_MAX_FORMATTED_ISSUES` (100) leaves and ends with `... and N more issues`;
  pass `max_issues=None` for all of them. Every line repeats its whole path, so an
  `errors="all"` failure of a deep value made a message (failing leaves x depth) long, which
  the MCP server sent back for invalid tool arguments. Paths are built only for the leaves
  written.
- `key_value_store.layer_file_system` escapes upper-case ASCII letters and a trailing `.` in
  file names (`user:Alice` is `user%3A%41lice`), so keys that differ only in letter case or
  by a trailing `.` no longer share one file on macOS or Windows file systems. Keys without
  either keep their file names. Upgrading: when the store opens it renames, once, each file
  0.6.5 named for a key with an upper-case letter or a trailing `.`, so every entry reads back
  as it did (`get`, `has`, `keys`, `size`, `remove` agree). Each file goes to the key its name
  spells, as 0.6.5's `keys` listed it; of a 0.6.5 file and a newer-named one for the same key,
  the more recently written stays.
- SQL `PersistedQueue` on MySQL: `offer` fails with a `PersistedQueueError` for an id or queue
  name longer than its column (1020 bytes of UTF-8), and a duplicate is skipped with
  `ON DUPLICATE KEY UPDATE` instead of `INSERT IGNORE`. `INSERT IGNORE` cut such an id to the
  column, so a second id sharing its first 1020 bytes was dropped while `offer` reported it
  stored. The other stores keep or refuse long ids already.
- Parsers and decoders take time linear in their input where some inputs cost quadratic time:
  URL hosts with non-ASCII labels (Punycode encoding and the joiner checks of IDNA), XML
  decoding (text split by CDATA sections or comments, chunks holding non-ASCII characters,
  markup in a chunk past `max_token_size`) and XML encoding of many events, TOML table headers
  of many dotted keys, YAML flow collections over many lines, `json_patch.apply` with many
  operations on one container, tar archives with global PAX records before many entries, and
  the `flags` of a JSON `RegExp`. The tar decoder's `Header.pax` is now a read-only mapping.
- A URL host whose non-ASCII domain is over 16 KiB of UTF-8 is invalid, as in Node's `URL`.
- Streamed AI responses fold their deltas in linear time: text and reasoning deltas into a
  prompt (`Prompt.from_response_parts`), OpenAI code interpreter code, and OpenRouter tool
  call arguments, which were parsed again after every delta.
- `big_decimal.from_string` (and `S.BigDecimalFromString`) reads at most
  `big_decimal.MAX_DIGITS` (30,000) significant digits by default, set with `max_digits`, and
  refuses an exponent past the safe integers before converting it.
- `yaml.parse` refuses an integer of more than `yaml.MAX_INTEGER_DIGITS` (1000) significant
  digits, and JSON parsing refuses one of more than `encoding.MAX_JSON_INTEGER_DIGITS` (4300)
  digits, with the parser's usual error (`ValueError`, a `SchemaError` through schemas) naming
  the limit. 0.6.5 read these integers in full, at superlinear cost; 0.6.6 refuses them past
  the limit. Hexadecimal or octal integer text past 1000 digits in `S.Number` and `S.BigInt`
  coercion reads as an infinity (or is no `BigInt`), as JavaScript's `Number` reads it; a
  long hexadecimal text in `Number` coercion raised `OverflowError`.
- `S.RegExp` decoding refuses a pattern whose character classes span more than 2**20 code
  points, or that nests too deeply to compile (a defect before), and no longer fills `re`'s
  cache with decoded patterns.
- The CLI's file prompt escapes control characters in file names, the target line and the
  submitted value, with the helper CLI output already escaped them with.
- Cluster workflows: a transient `PersistenceError` while a workflow starts a child workflow,
  or while it reads a `DurableDeferred` it awaits, is retried without bound (backing off to
  once a minute) instead of failing the workflow with a defect, as in Effect 4.1.4 (#10311,
  #10356). Deferred reads gave up after three tries. Reads of the interrupt signal made by
  shutdown cleanup still give up after three, so shutdown is not held by an outage, and a
  top-level `execute` still dies at once. `tests/test_cluster_engine_or_die_sites.py` pins
  each place the engine turns a storage failure into a defect to the one Effect has.
- Workflows: `workflow.layer_memory` keeps the `add_finalizer` finalizers of a run resumed
  after a defect until the execution completes; the new run forked from the execution scope
  the defect had closed, so they ran at once. Run setup is serialized, so concurrent wakes
  can't start two runs, as in Effect 4.1.4 (#10393).
- Workflows: `into_result` interrupted right after the handler starts runs the handler's
  cleanup before the workflow's finalizers; only the join is interruptible now, as in Effect
  4.1.4 (#10472). A test interrupts it after every op of the run, not only at Effect's one
  point.
- `RateLimiter`: a fixed-window `consume` with `on_exceeded="fail"` admits at most `limit`
  per `window`: the first admission opens a window of the full `window` that later admissions
  don't extend. Each admission extended it by `window / limit`, so the window let in more
  than `limit` and `reset_after` read short. Fixed in the memory and Redis stores, as in
  Effect 4.1.4 (#10390). A test replays random call sequences on both stores and compares
  them, so the Lua script and the memory store can't drift apart again.
- SQL `PersistedQueue`: a failed job is retried no earlier than its retry schedule's delay on
  SQLite and MySQL (it could come up to a second early), and a delayed offer on SQLite no
  longer waits a second more than its delay. SQLite keeps `visible_at` deadlines and the
  readiness check on one millisecond clock, as in Effect 4.1.4 (#10318).
- `headers.from_input` joins repeated names in `(name, value)` pairs with `", "`, as Effect
  4.1.4 does (#10450); it kept only the last value.
- A server request with no body streams as empty, as in Effect 4.1.4 (#10506). Its `stream`
  failed with "can not create stream from empty body", which included every bodyless request
  the live server received.
- `prompt.integer` and `prompt.number` keep a typed minus sign when a zero follows it, as in
  Effect (#10558): typing `-0.05` submitted `0.05` and `-07` submitted `7`.
- The static server matches `If-None-Match` entity tags that contain commas, as Effect 4.1.4
  does (#10066): the header was split on every comma, so `"v1,part"` never matched (200
  instead of 304) and `"v1", "part"` could. Both `If-Match` and `If-None-Match` now read the
  list whole, and a malformed list matches nothing.
- Shell completions, as in Effect 4.1.4: a variadic argument without a positive minimum is
  no longer marked required (#10375); repeatable flags (`at_least`, `between`, `at_most`
  above 1, `key_value_pair`) stay offered after first use in Bash, Zsh, Fish and PowerShell
  (#10428); subcommand names containing `:` complete in Bash and are escaped for Zsh's
  `_describe` (#10417).
- The RPC stdio server exits 0 under `run_main` once stdin closes and its responses drain, as in
  Effect 4.1.4 (#10475); it ended with a plain interruption, which `default_teardown` reports
  as 130. A failed write still exits non-zero, and an output already interrupted no longer
  interrupts the server again.
- The live server's shutdown no longer waits out `graceful_shutdown_timeout` while WebSocket
  clients are connected, as in Effect 4.1.4 (#10405): WebSockets get a close with 1001 (Going
  Away) as soon as shutdown starts, other upgraded connections are ended, and any still open
  after the wait are destroyed. A connected, responsive client held a 5-second shutdown for
  the whole 5 seconds and got 1001 only when its handler was interrupted. This holds from the
  moment the `101` is written, even when shutdown starts before the server's write of it
  returns.
- A request scope moved to a streamed body with `scope_transfer_to_stream` closes once both the
  request (middleware and tracing included) and the body have finished, with the body's exit,
  as in Effect 4.1.4 (#10366). It closed as soon as the body ended, before the middleware and
  the server span. A body transferred twice keeps its first exit, and `to_web_handler` now
  transfers through the same path.
- `HttpClient.with_scope` owns every request the client sends while it executes, as in Effect
  4.1.4 (#10363): redirect hops and requests rewritten by middleware stay open until the scope
  closes on whichever side of `follow_redirects` it is, concurrent runs of one response effect
  get their own owners, a request interrupted before its response is aborted, and one sent
  after the scope closed is aborted before the transport starts it. Requests another client
  sends while this one executes now belong to the scope too.
- `HttpClientError` reasons redact their URL with the `url_params.CurrentRedactedNames` active
  when they are made, and the client adds the executing fiber's names to errors a transport
  fails with from another thread and to errors read from its responses, as in Effect 4.1.4
  (#10006). A logger or exporter rendering the error later, on another fiber, showed the
  secret query values. Rendering still adds the rendering fiber's names; equality ignores
  them.
- `HttpClientErrorSchema.message` is its cause's message, or its kind when the cause has none,
  as in Effect 4.1.4 (#10496), so an `RpcClientError` for an HTTP failure says what failed. It
  was empty.
- A framed RPC HTTP response drains while its batch is dispatched, as in Effect 4.1.4 (#10424):
  a batch with more responses than `stream_buffer_size` hung, and a dispatch that failed (a
  payload decode defect, a reused request id) left the response waiting forever. Such a
  response now fails with the dispatch's cause and its requests are interrupted.
- `--wizard` replaces the flags and arguments typed for the selected command with its answers
  and keeps inherited flags, short clusters included (a numeric alias is written `--4`), as in
  Effect 4.1.4 (#10529). The typed ones were repeated before the answers. The wizard puts `--`
  before a leaf command's arguments, so an answer such as `false` is not read as the value of
  a boolean flag before it; `command.wizard` returns that `--` too.
- The HTTP client sends no trace headers and makes no span when `TracerEnabled` is off, as in
  Effect main (#10627). It sent the no-op span's `noop` ids.
- `Toolkit.handle`: a stream stopped early dies with the defects of its tool handler's
  interrupt finalizers instead of dropping them, as in Effect 4.1.4 (#10437).
- MCP: `resources/read` includes the registered `mimeType` when a resource returns a string or
  bytes, as in Effect 4.1.4 (#10398).
- MCP: `tools/list`, `resources/list`, `resources/templates/list` and `prompts/list` fail with
  InvalidParams "Unknown cursor" when given any cursor, including `""`; lists are one complete
  page, as in Effect 4.1.4 (#10447).
- MCP: progress for a request is dropped once the request is answered, cancelled or its client
  disconnects, also when it was already queued behind a slow stdio, RPC or HTTP client.
  Background progress is kept, as in Effect 4.1.4 (#10509).
- MCP: an open 2026-07-28 `subscriptions/listen` over stdio completes with a
  `resultType: "complete"` result carrying its subscription id when stdin ends; it was
  interrupted without an answer. Requests in flight still drain, as in Effect 4.1.4 (#10477).
- MCP: on 2026-07-28 over HTTP, a tool hidden by `McpServer.visibility` answers "Tool 'X' not
  found" before its `Mcp-Param-*` headers are checked, instead of a 400 header mismatch, as in
  Effect 4.1.4 (#10504).
- OpenAI WebSocket mode: a client transform that fails to prepare the `/responses` connection
  request fails the response stream with an `AiError` instead of dying, building the layer no
  longer fails when priming the socket fails, and later turns reuse the request the connection
  was opened with, as in Effect 4.1.4 (#10512).
- Anthropic: encrypted code execution results (`encrypted_code_execution_result`) decode as
  successes and are sent back in the next request; they were failures and were dropped from the
  replayed history, as in Effect 4.1.4 (#10322).
- Anthropic: successful text editor results of code execution 20250825 (view, create,
  str_replace) are sent back in the next request; they were dropped, so Anthropic rejected the
  history, as on Effect main (#10552).
- Anthropic: non-strict tools (`strict_json_schema=False`, `Tool.Strict` false, or a model
  without strict tools) are advertised with their plain JSON Schema and their calls decode with
  it, keeping optional properties, constraints, records and explicit `null`s; they got the
  strict Anthropic schema and lost `null` parameters, as in Effect 4.1.4 (#10499).
- Anthropic: with native structured output, a response that stops on a tool call finishes as
  `tool-calls`; it finished as `stop`, so the toolkit didn't run. Only the structured-output
  response tool maps to `stop`, as in Effect 4.1.4 (#10527).
- `to_codec_openai` / `to_codec_anthropic`: optional records and tuples encode and decode (they
  failed "Expected object" / "Expected array | null"), and an optional property whose schema
  already accepts `null` gets one `null` branch instead of `anyOf [T, null, null]`, as in
  Effect 4.1.4 (#10502, #10522).
- OpenAI: successful `Shell` / `LocalShell` results are sent as the tool's `output`, not wrapped
  in another `{output}`, as in Effect 4.1.4 (#10321).
- OpenAI: `generate_object` ignores `phase: "commentary"` messages, which were joined with the
  answer and broke JSON decoding; text output keeps them, as in Effect 4.1.4 (#10329).
- OpenAI: streamed `shell_call` tool calls use `call_id` as their id (the item id stays in
  metadata), so a stored chat answers them with the right `call_id`, as in Effect 4.1.4
  (#10358).
- OpenAI: with item references, a stored provider-executed call and its result send one
  `item_reference`, not two, as in Effect 4.1.4 (#10429).
- OpenAI: plain-text requests no longer send `text: {format: {type: "text"}}`, which some
  OpenAI-compatible Responses backends reject; `text` carries only `verbosity` unless there is a
  JSON format, as in Effect 4.1.4 (#10484).
- OpenAI, OpenAI-compatible: a non-strict tool (`strict=False` or `strict_json_schema=False`) is
  advertised with its plain JSON Schema and its call parameters are taken as sent; records were
  sent as arrays of pairs and optional keys as required nullables, as in Effect 4.1.4 (#10533).
- OpenAI-compatible: the system prompt is sent as `developer` only for `o<digit>`, `gpt-5`,
  `codex-` and `computer-use` models; `olmo-2`, `openai/gpt-oss-120b` and `openai/o3` get
  `system`, as in Effect 4.1.4 (#10516).
- OpenRouter: tool call parameters are decoded with the codec their schema was sent with, so
  record and tuple parameters on OpenAI and Anthropic models reach the handler (they failed
  "Expected object"). Strict tools on other models get OpenAI's strict schema, and a dynamic
  tool's own JSON Schema is sent unchanged, as in Effect 4.1.4 (#10486).
- OpenRouter: a tool call without an `id` gets `<response id>_tool_<n>`, and a streamed tool
  call without an `index` uses its position in the chunk; both failed to decode, as in Effect
  4.1.4 (#10505).
- OpenRouter: a response with tool calls but no finish reason finishes with `tool-calls`, so the
  tools run (it finished `other`); a stream does so only when every call parsed, as in Effect
  4.1.4 (#10489).
- OpenRouter: a stream that ends before a tool call's parameters are complete fails with
  `ToolParameterValidationError` unless it finished with `tool-calls`; the call was dropped
  silently, as in Effect 4.1.4 (#10488).
- OpenRouter: an empty tool-call fragment after its call completed is ignored; it failed the
  stream with `InvalidOutputError`, as in Effect 4.1.4 (#10487).
- OpenRouter: empty streamed `content` deltas no longer split reasoning into several parts or
  emit empty text deltas, as in Effect 4.1.4 (#10370).
- OpenRouter: base64 string image and file data is sent as a `data:` URL; it was sent bare, as
  in Effect 4.1.4 (#10485).
- A `TaggedError` that was raised in an effect body (a defect, as a throw in Effect's `gen`
  is, so `catch_tag` never sees it) is printed with a hint to fail with it instead:
  `return (yield from Error(...))` or `fx.fail(error)`. `Cause.pretty()` adds the hint after
  the defect, and `run_blocking` adds it as a note to the error it raises. The cause itself is
  unchanged, and a `TaggedError` made a defect by `or_die` gets no hint.
- `eff.catch_tag(...)` and the other combinators that are functions for `.pipe` on purpose
  (`catch_reason`, `catch_reasons`, `catch_no_such_element`, `provide`, `provide_context`,
  `provide_service`, `provide_service_effect`, `update_context`, `with_execution_plan`) raise an
  `AttributeError` showing the `eff.pipe(fx.catch_tag(...))` form, instead of naming a private
  class and suggesting `catch_all`. Other missing attributes name `Effect` rather than a private
  class. pyright still reports them as unknown attributes (`tests/type_checks.py`).
- An `async def` given to `@fx.fn`, `fx.fn_untraced`, `fx.fn("name")` or `@fx.gen` dies with a
  `TypeError` that says to write a `def` and run the coroutine with `yield from fx.from_async(f)`,
  and its coroutine is closed, so Python no longer warns that it was never awaited.
- A test timeout given as a bare number (`@testing.effect(timeout=10)`, 10 milliseconds, as in
  Effect) fails with a note saying it was milliseconds and how to write seconds.
- A member that `layer.mock` was not given dies with `UnimplementedError` naming a given member
  it may be a typo of (`... Unimplemented method "send"; layer.mock was given "sned": a typo?`).
  Without a close match the message is Effect's, as before.
- The `ImportError` of a missing extra gives the `pip install "pyfect-dev[extra]"` form next to
  `uv add`.
- The README's links and images are absolute, so they work on PyPI, which shows the README
  without the repository around it; `tests/test_readme.py` keeps them that way and runs the
  quick look, which now prints its greeting.
- `encoding.base64`, `base64_url` and `hex`'s `decode_string` keep a leading U+FEFF, as in
  Effect 4.1.4 (#10350); they dropped it as a byte-order mark, so `decode_string(encode(s))`
  lost the first character of a string starting with one. The shared UTF-8 helper now takes
  `ignore_bom` with no default, and `tests/properties/test_encoding_properties.py` round-trips
  generated text through every module.
- Schema: a struct reading an instance treats a field named after a member every instance
  inherits from `object` (`__doc__`, `__str__`, `__class__`, `__module__`, ...) as present only
  when it is the instance's own attribute (its `__dict__` or a slot), as Effect 4.1.4 does for
  `Object.prototype` members (#9612). An optional `__doc__` field failed with "Expected string"
  on a plain instance, and a required one read the class's docstring. Other inherited
  attributes, such as properties, are still read. `tests/oracle/test_schema_object_members.py`
  checks every such name, interpreted and compiled.
- Schema: `to_equivalence` and `to_formatter` select a Record's keys by its key's decoded
  side, as in Effect 4.1.4 (#10453). With a transformed key (lowercase encoded, uppercase
  decoded) the equivalence found `{"A": 1}` equal to `{"A": 2}` and to `{}`, and the formatter
  wrote `{}`. `ast.IndexSignature.selects_decoded` is the decoded-side test, beside `selects`
  for keys of an input to decode.
- `encoding.xml.decode` fails with a `Syntax` error rather than `Unsupported` on an encoding
  declaration the bytes contradict (UTF-16, UTF-32, UCS-2 and UCS-4, or US-ASCII and
  ISO-8859-1 after a UTF-8 byte order mark), and no longer reads a document starting with a
  byte order mark as US-ASCII, as on Effect main (#10574). One function classifies a
  declaration against the bytes, and `tests/test_xml_encoding_declarations.py` checks every
  spelling with and without a byte order mark.
- Schema: `TemplateLiteral` and `TemplateLiteralParser` accept `S.Enum` parts, matched by the
  text of the enum's values (a parser decodes the member), and their JSON Schema pattern is
  the alternation of those values, as on Effect main (#10576). They raised `ValueError:
  Invalid TemplateLiteral part Enum`, though the part's type accepted them. An enum without
  members matches no string. `ast._template_literal.PART_KINDS` lists the part kinds, and
  `tests/test_template_literal_parts.py` runs one part of each kind through matching, the
  parser, the strategy, the JSON Schema pattern and representations.
- `representation.from_json_schema_document` and `from_json_schema_multi_document` drop a
  `contentSchema` annotation holding a `$ref` or `$dynamicRef`, which pointed at a definition
  the annotation doesn't carry; reference-like data under `const`, `enum`, `examples` or
  property names is kept, as in Effect 4.1.4 (#10426). One walk over a schema's subschema
  positions (`json_schema._model.subschemas`), built from the keyword classification, serves
  this check and the importer's pointer walk.
- The JSON Schema importer intersects unions whose alternatives differ by a required literal
  property (referenced objects included), accepts a typed `additionalProperties` that covers
  the declared properties, keeps a union's `oneOf` mode when it resolves a reference inside
  it, keeps examples on the whole intersection instead of each distributed branch, imports a
  recursive definition intersected with itself, and rejects other recursive intersections
  with an error instead of failing, as in Effect 4.1.4 (#10521). A recursive definition that
  can't be resolved fails with "Cannot resolve recursive definition ... during normalization."
- Schema code generation (`representation.to_code_document`) prints an annotation value only
  when it and every value inside it is exactly a `None`, `bool`, `int`, `float`, `str`,
  `list`, `tuple` or `dict`, as Effect 4.1.4 prints only plain objects and arrays (#10532).
  An `IntEnum` member printed as `<C.A: 1>`, which isn't Python, and a `namedtuple`,
  `OrderedDict`, `Counter` or `MappingProxyType` printed as a plain list or dict; such
  annotations are now omitted. `tests/properties/test_code_value_literals.py` checks that
  whatever is printed evaluates back to the value.
- `date_time.zone_named` keeps the id it is given, a renamed zone's new or old name included
  (`Europe/Kyiv`, `Asia/Kolkata`, `Etc/UTC`), as Effect 4.1.4 does (#10439); the casing still
  comes from ICU when the two differ only in case (`europe/london` is `Europe/London`). It
  named the zone with the id ICU resolves it to (`Europe/Kiev`, `Asia/Calcutta`, `UTC`), so
  `zone_to_string`, `format_iso_zoned` and the zone schemas wrote another name than the one
  given. Zones ICU resolves to the same id are equal and hash alike (`Europe/Kyiv` equals
  `Europe/Kiev`), and the local zone is still named by ICU's id, as in Effect.
  `tests/oracle/test_icu_zones.py` checks every id ICU knows.
- `date_time.make` and the other parsers of a `DateTime.Input` string read a string ending in
  `UT`, `UTC` or a US zone abbreviation (`EST`, `pdt`, any case) in that zone, as on Effect
  main (#10562); they added a `Z` after it, so the string failed to parse. The trailing-zone
  check is now built from the date parser's own zone words.
- The `encoding.csv` decoders emit the records completed before an error in the same chunk,
  then fail, as in Effect 4.1.4 (#10456); they dropped them, so the records seen depended on
  how the input was split into chunks. A property test now checks that every split gives the
  same records and error.

### Performance

- `find_my_way` escapes each `%25` in a request path by appending, as in Effect main
  (#10619): it copied the whole path for every one, so a path of many `%25` took quadratic
  time (about 500 ms for 50,000 of them, now about 30 ms).

### Docs

- Effects: a callout that a bare-number duration is milliseconds, and a "Common mistakes"
  section (`time.sleep`, `run_blocking` in a coroutine or notebook, `yield` for `yield from`,
  `await eff`, `@fx.fn async def`, `eff.catch_tag`, `raise` for a typed failure).
- Errors: a callout that a raised `TaggedError` is a defect, and how to fail with it. The
  introduction says pyright checks typed errors, not raised exceptions.
- Installation: start a project with `uv init`, add pyright as a dev dependency, the pip
  equivalent, and why `uv add` needs a `[project]` table; `hello.py` prints its greeting.
- Services: mocking a service with `layer.mock`, and what a misspelt member does.
- Testing: a bare-number timeout is milliseconds; the `pyfect_timeout` ini option is seconds.

## 0.6.5 (2026-11-14)

### Deprecated

- `schedule.Continue`, `Stop` and `Decision` warn. Schedules now step as Effect's do, with a
  `Pull` that succeeds with `(output, delay)` and fails with `cause.done(output)` to stop, and
  the public step functions translate: `from_step` still takes a step deciding `Continue` or
  `Stop`, and `to_step`, `to_step_with_metadata` and `to_step_with_sleep` still hand them back.
  They are removed in 0.7.0, where those three hand back Effect's steps.

### Added

- `sql.client.make(begin=...)` starts outermost transactions for databases that need more than
  one statement, and `sql.client.active_transaction_connection(level)` gives a transaction
  level's connection or fails once it has ended, for drivers that read their transaction
  service directly, as in Effect 4.1.4 (#10267, #10434).
- `schedule.from_step` and `from_step_with_metadata` take Effect's steps too: a step that
  succeeds with `(output, delay)` to recur and fails with `cause.done(output)` to stop.
- `pyfect.testing.test_clock_with(f)`, Effect's `TestClock.testClockWith`.
- `for_each(..., discard=True)`, Effect's `forEach` `discard` option: runs every item and
  keeps no results.

### Fixed

- `NaN`, `inf` and `-inf` are written `null`, as `JSON.stringify` writes them, wherever
  Effect writes JSON with it: `ndjson.encode` / `encode_string`, `json_array.encode` /
  `encode_string`, `WebResponse.json_of`, the `json` and `ndjson` RPC serializations, the SQL, Redis and key-value backing persistence stores, MySQL JSON
  parameters, ClickHouse `JSONEachRow` inserts and the cache keys of GraphQL resolvers.
  These raised `ValueError` or failed with an encode error. `pyfect._json_text.stringify`
  now always writes `null` (its `null_non_finite` flag and `js_stringify` are gone), so no
  call site can pick the strict form by mistake, as GraphQL variables and
  `S.UnknownFromJsonString` did before (GQL-1, 0.6.2). Schemas that reject non-finite
  numbers before writing (`HttpApi` payloads and responses, JWT claims, cluster messages)
  are unchanged, as in Effect. `tests/test_js_formatting_guard.py` now also catches
  `json` imported through `__import__` / `importlib` and other JSON libraries (`orjson`,
  `ujson`, `simplejson`, `rapidjson`, `msgspec.json`).
- SQL: statements, `reserve` and nested transactions from a fiber that outlives the transaction
  it was forked in fail with an `SqlError` ("the transaction has already ended") instead of
  running on the released connection, which may already be in another transaction; ending a
  savepoint ends it for its fibers too. A savepoint whose parent ended leaves the connection
  alone, as in Effect 4.1.4 (#10433, #10434). This covers SQL Server's `call` and
  `without_transforms()` and libSQL's `reserve`, which inside a transaction now gives its
  connection (on a local database it waited for the transaction's own permit forever).
- SQL: a nested `with_transaction` waiting for the savepoint can be interrupted; the savepoint
  and its cleanup still can't, as in Effect 4.1.4 (#10435).
- SQL: a savepoint is not released when an ancestor transaction ended while it rolled back,
  as in Effect 4.1.4 (#10508).
- SQL: `without_transforms()` also drops a client's `transform_query_names` when it has no
  result transform, and `CurrentTransformer` gets the client that built the statement, as in
  Effect 4.1.4 (#10454).
- MySQL: a `BeginTransaction` starting with `SET TRANSACTION` (an isolation level) runs just
  before `BEGIN`; it replaced `BEGIN`, so no transaction was started, as in Effect 4.1.4
  (#10267).
- SQL Server: `insert(...).returning(...)` and `update_values(...).returning(...)` bind the
  returning clause's parameters after the row values, as in Effect 4.1.4 (#10452).
  `tests/test_sql_placeholder_binding.py` checks every helper on every dialect.
- SQL Server: `sql.model` repository `update` returns the row (`OUTPUT INSERTED.*` before
  the `where`); it wrote a trailing `returning *`, which SQL Server refuses, as on Effect main
  (#10563).
- PostgreSQL: the server ending the session inside a nested transaction keeps the typed
  `SqlError` instead of becoming a defect: rollbacks on a dead session are skipped, as in
  Effect 4.1.4 (#10291).
- PostgreSQL: the client's span name and `db.namespace`, `server.address` and `server.port`
  follow the connection `url` (and its query parameters); the namespace defaults to the user.
  A URL-only config reported `postgres`, `localhost` and 5432, as in Effect 4.1.4 (#10500).
  An invalid config now fails `pg.make` at once, not at the first statement.
- Loops written as nested functions that reached themselves through a closure (by name, or
  through a variable or object holding something built from them) formed a reference cycle, so
  the last value, error or pull they handled stayed alive until the cycle collector ran: an HTTP
  response kept its socket open that way. Affected were stream and channel operators (`filter`,
  `filter_map`, `map_accum`, `flat_map`, `switch_map`, `catch_cause`, `rechunk`, `drop`,
  `debounce`, `throttle`, `repeat`, ...), the CSV, JSON array, NDJSON, XML, SSE, tar, zip and
  binary decoders and encoders, schedule combinators, `PersistedQueue.take`, `Queue` and
  `PubSub` takes, `Pool`, `RcMap`, socket writes, the live server's readers, SQL pools, config
  loading, shared layer builds (which kept a run's result), and recursive walkers such as schema
  and logger formatting. They are now module-level functions or methods on a small state object.
  `tests/test_closure_cycles.py` fails for any nested function in `pyfect` that reaches itself
  through a closure cell, and `tests/test_release_*.py` check that the public loops free what
  they handled once the run ends, with the cycle collector off. The live server's request
  `upgrade` still refers to its request this way; the fix changes its signature, so it waits
  for 0.7.0.
- Fibers yield where Effect's do under `MaxOpsBeforeYield` (#6): ops are counted and the budget
  checked as in Effect 4.1.2's run loop. A run counts from zero, the check comes before every op
  (a budget under 3 livelocks in Effect, so pyfect runs it as 3), a resumed run counts the
  yield's continuation and the paused op, every 32nd `map` (Effect's `succeedWith`) goes back
  through the loop, and exits handed straight to a continuation are free. The combinators that
  run under it are built as Effect's are, op for op: `for_each` and `all` (one child per item,
  Effect's `iterateConcurrentImpl`, and a `whileLoop` one at a time), `while_loop`,
  `as_`/`as_void`, `on_exit`, `acquire_release`, `acquire_use_release` and the masks, `race` and
  `race_all`, `match`/`match_cause`/`option`/`exit`/`result`, semaphore `with_permits`,
  `release` and `resize`, `Scope.close`, `Fiber.interrupt` and `await_exit`, a channel's build,
  the clock accessors (`clockWith`), the live and test clocks' `sleep` and `TestClock.adjust`,
  queue `take` and `poll` (`suspendTake`), queue constructors and `fork`. A failing op meeting
  an interrupt keeps its cause and gains the interrupt, and an interrupted wait runs its
  canceler as Effect's `asyncFinalizer` does. Two fibers under a small budget now interleave
  exactly as in Effect (`tests/oracle/test_max_ops_interleaving.py`, recorded from Node), and
  the runtime differential tester runs its programs (not its harness) under budgets from 3 to
  200 rather than an unlimited one, and its checked-in corpus has 1152 programs: none of 19,000
  generated programs differ (seeds 7, 11, 23, 31 and 47), from 947 of 3000 before. Built op for
  op as well: schedules and everything that steps them (`retry`, `repeat`, `schedule`, the
  stream and channel schedule operators), the channel merge (its loop and its workers' end, one
  generator each as in Effect), sequential `flat_map` (Effect's `flatMapEager`), concurrent
  `map_effect`, `Stream.map`, `Channel.suspend`, iterator pulls, `Fiber.join`, `exit`/`result`,
  `scoped` and a scope's lone finalizer, and an interrupt arriving at a wait or at
  `set_interruptible`. A result a step claimed (a taken permit or item) that the fiber pauses
  before now reaches its continuation before an interrupt that landed in the pause, as in
  Effect, and a raising `should_yield` is a defect rather than Effect's endless retry.
  Interleavings change under the default budget (2048) too, since fibers now yield at other
  ops.
- `retry_transient` reads a `Retry-After` HTTP date against the schedule's clock in epoch
  milliseconds, as Effect's `retryAfterOf(input, now)`. It multiplied the time by 1000 first, so
  a date in the future read as long past and the retry did not wait for it.
- Integers past 4300 digits, which Python's `int` and `str` refuse and JavaScript reads and
  prints in full, no longer crash the parsers that read them: `BigDecimal.format()` and
  `normalize()` of a decimal with that many digits (it parsed, then raised), ISO 8601
  durations (`duration.from_iso`, `DurationFromString`) and their `format_iso`, YAML
  integers, `JSON.parse` (`schema.parse_json` and the other JSON readers), `Int` record keys
  in JSON and representation documents' `bigint` values. Each is read in full, as in
  Effect; an `Int` key or a template literal `BigInt` past what its schema accepts is a
  `SchemaError` where it was a defect. `big_decimal.from_number` of an `int` too large for a
  float is that integer. Conversions go through `pyfect._digits.to_int` and
  `pyfect._js.int_text`, which take time a little above linear (a million digits in under
  a second to read, two to print), and `tests/fuzz/test_long_digit_runs.py` replays every
  fuzz target's corpus with its digit runs stretched past 4300. Found by fuzzing (text).
- `tests/cross_run`'s `RcRef.get` case failed now and then on CI with "3 resources live at
  once": it allowed at most 2, which is wrong for `RcRef` and `RcMap` (and so `LayerMap`). As
  in Effect 4.1.2, once a key's last holder lets go the key is free again before that
  holder's release has run, so a `get` from the same run meanwhile acquires afresh and any
  number of releases can still be running; a `get` from a run on another thread waits for the
  release (0.6.4). Run under Node, Effect holds 3 at once
  when two releases wait on a gate, and so does pyfect (`tests/test_resource_edges.py` pins
  both). The cases now check what does hold: while a resource is held, no newer one is
  acquired for its key.
- What a run starts goes on after its caller returns, as on Effect's always-alive scheduler.
  A fiber ran only while the run that forked it was being driven, so once `fx.run_blocking`
  returned, whatever it left waiting stopped for good, silently. In threaded handlers: 0 of
  20 tasks forked into a `FiberSet` ran and closing its scope hung; a timeout could not end a
  wait on a `Cache`, `RcMap` or `RcRef` lookup whose starter's run had ended, and one timed
  out request on a hot `Cache` key made every later one time out; a `Pool` made in a short run
  had no items after two invalidations, a TTL pool never grew past its minimum, and an `RcMap`
  with an idle time to live never released and hung its scope's close. Now, when
  `run_blocking`, `run_sync` (whose waiting fiber goes on, as Effect's `runSync`), a
  `ManagedRuntime`'s sync runs or a standard schema's validation return, their scheduler is
  adopted by one background scheduler (`scheduler.BACKGROUND`, a daemon thread started when
  first needed): its ready tasks and timers move there, and every later wake goes there too.
  `tests/cross_run/test_run_ownership.py` ports each dogfood repro, on both builds, and
  `tests/test_run_adoption_guard.py` allows only the functions that hand their scheduler on to
  drive one and checks every public run function leaves a waiting fork running;
  `tests/test_decided_results.py` wakes a returned run's parked fiber from another thread
  and interrupts it first, for every primitive, as 0.6.4 does for a run still driven. Docs:
  [Threads](/docs/threads#sharing-state-between-runs) drops the limits this lifts. Found by
  dogfooding (pyfect-39).
- A `ManagedRuntime`'s `run_blocking` calls on different threads no longer wait for each
  other. They shared one scheduler and held the runtime's lock for a whole drive, so a quick
  run waited for the slowest one in flight (1.8 s behind a 2 s run), and a run waiting for
  another thread's run of the same runtime (`runtime.run_blocking(fx.blocking(serve))`)
  deadlocked. Each sync run now has a scheduler of its own and no lock, and `run_fork` and
  `run_callback` called outside any run start on the background scheduler instead of waiting
  for a sync run to drive the runtime's. Found by dogfooding (pyfect-39).
- `race`, `race_first`, `race_all`, `race_all_first` and the timeouts interrupt the losers as
  soon as the winner settles the race, not when the racing fiber next runs, as in Effect 4.1.4
  (#10367). A loser that finished in that gap had its result dropped: `queue.take()` racing
  another effect could take an item and lose it.
- `Queue.sliding(0)` hands an offered item to a waiting taker, and drops it when no taker is
  waiting, as in Effect 4.1.4 (#10312, #10354); it kept the newest item in a slot and never
  woke the taker. A zero-capacity `bounded` or `dropping` queue no longer accepts an `offer` or
  `offer_all` with no new taker after an `offer_all` was handed to the only one (Effect's
  `free` is takers minus items buffered for them), which `Stream.buffer(capacity=0)` relied on.
- `ScopedCache.get` and `get_option` waiting on a lookup are interrupted when the cache's
  scope closes before the lookup finishes, and the late entry's scope is closed, as in Effect
  4.1.4 (#10451). They succeeded with a value whose resources were already released.
- `ScopedCache` lookups (from `get` and `refresh`) no longer inherit the requester's span: an
  entry's finalizers kept that span, and the response it ended with, alive until the entry
  left the cache, as in Effect 4.1.4 (#10317). Spans made inside a lookup are children of the
  span active when the cache was made.
- `RcMap` measures idle time, `touch` included, on the clock of the context the map was made
  in, and runs its idle timers in that context, as in Effect 4.1.4 (#10324). It used the
  clock and context of the last borrower to release the entry.
- `Pool.make_with_ttl` with the `"usage"` strategy retires an idle excess item one
  `time_to_live` after its last release (or within `time_to_live` of it becoming excess or
  unreserved), as on Effect main (#10543). It checked once per `time_to_live`, so retirement
  took up to twice as long.
- `config_provider.from_env()` copies `os.environ` when its first lookup runs, not when the
  provider is made, and providers derived from it share that copy, as on Effect main (#10567).
  `from_env(env)` with a mapping is unchanged.
- A fiber on a custom `EffectScheduler` whose `should_yield` says yes after one or two steps
  makes progress: a run resumed after an automatic yield takes the step it saved before asking
  again, as in Effect 4.1.4 (#10463). It yielded again before every step and never finished.
  The same applies to `MaxOpsBeforeYield` of 1 or 2 when `run_fork` is given a scheduler.
- A dispatcher whose `schedule_task` raises during an automatic yield makes the fiber die with
  that defect, as in Effect 4.1.4 (#10463). The exception escaped to whoever was running the
  fiber, killing the forking parent instead and leaving the child stuck.

### Performance

- `Queue.take`, `peek`, `await_done` and `take_between` re-enter through methods rather than a
  fresh closure per call.
- A `Semaphore` queue no longer costs time quadratic in its length: queueing a request,
  releasing and leaving stop scanning once no queued request can fit in the free permits, as
  on Effect main (#10595). Queueing 2,000 requests that cannot fit visited 4,000,000 waiters;
  it now visits 2,001.

## 0.6.4 (2026-11-14)

### Added

- `Stream.split_lines_within(max_length)`, as `channel.split_lines_within`: a line longer
  than `max_length` characters fails the stream with `LineTooLongError` as soon as that much
  of it has arrived. `split_lines` holds a line until its break arrives, so a peer that never
  sends one grows memory without bound (32 MiB without a newline peaked at 64 MiB).
- `max_line_length` on `ndjson.decode_string`, `duplex_string`, `decode_schema_string` and
  `duplex_schema_string`, failing with `"LineTooLarge"`, as `max_line_bytes` does for the byte
  decoders. Both stay unbounded by default, as in Effect.

### Fixed

- A `timeout` (or any interrupt) of a fiber waiting for something a run on another thread
  then gave it no longer goes on as if it had not timed out. The woken fiber's resume used to
  run after its interrupt was already decided, so the caller saw a timeout while the rest
  happened anyway: `Queue.take_between` took items that were then lost (the dogfood soak on
  0.6.2 lost 6,586 of 1.95M in 60 minutes on 3.14t; Effect none of 3.1M); `Semaphore.take`
  and `PartitionedSemaphore.take` kept permits nobody would give back, leaving the semaphore
  stuck; `with_permits`, `Pool.use` and `Latch.when_open` ran their effect; `Pool.get` and
  `RcRef.get` kept a lease or a reference; `SubscriptionRef.update` and `set` stored and
  published; whatever followed a `Deferred.wait` or a fiber's `join` ran. A wake-up now
  decides nothing until it runs in the woken fiber's own step (`_Retry`, `WOKEN`,
  `woken_with`), and an interrupt that reaches the fiber first wins over it, as in Effect,
  where both happen in one order on one thread. Found by dogfooding (soak, gap probe).
- A `Queue.offer` or `offer_all` to a full queue, and a `PubSub.publish` to a full
  back-pressure hub, that times out no longer delivers its items anyway (13 of 56 timed-out
  offers and 135 of 574 timed-out publishes reached a consumer in the soak; Effect: none of
  6,897). The queue and the hub decided such an offer for the waiting fiber, even one of
  another run, whose timeout could already have won. They still do for a fiber of their own
  run, which runs at once as in Effect; a fiber of another run is now woken to add its items
  itself, in its own step, keeping its place in line meanwhile.
  `tests/test_decided_results.py` runs every claiming case, and each primitive above, with
  the wake-up coming from another thread's run. Found by dogfooding (soak).
- A `ScopedCache.get` or `Cache.get` joining a lookup in progress, just as its only other
  waiter left (a timeout), failed with `Interrupt` although nobody interrupted it: the cache
  counted the caller only after letting go of the lock it found the entry under, so the
  leaving waiter saw nobody waiting and interrupted the lookup. The caller is now counted
  under that lock, as Effect finds and counts in one step. Found by dogfooding (gap probe).
- An `RcRef.get`, or an `RcMap.get` of the same key, from a run on another thread no longer
  acquires a new resource while the last one's release runs, including `RcMap`'s release on
  `invalidate` or idle expiry (`RcRef`: 20 times in 25 s on 3.14t in the gap probe). In Effect
  a release that does not suspend ends before any other fiber runs; such a get now waits for
  it, while a get from the releasing run still acquires afresh, as in Effect.
- ClickHouse map settings (`additional_table_filters` and the other `Map(String, String)`
  settings given to `with_clickhouse_settings` or `insert_query`) escape quotes and
  backslashes in their keys and values. They were written as `{'k':'v'}` as they were, as
  `@clickhouse/client` writes them, so a filter holding a string literal was refused by the
  server, and a key or value with a quote ended its literal early, letting the rest be read as
  more of the map. Every ClickHouse literal the driver writes now goes through one quoting
  function, and `tests/test_clickhouse_quoting.py` keeps hand-written quoting out of the
  driver; the round trip runs on a real server.
- A MySQL connection that failed part way through reading a result is closed, so the pool
  replaces it. A failure other than the server's own error (a lost connection, a value that
  could not be read) left the rest of the result unread on a connection the pool kept, so the
  next statement on it failed with "Packet sequence number wrong", or read the old result.
  `tests/oracle/test_mysql_failed_reads.py` fails every packet of a result in turn, on the
  prepared, text and stream paths, and runs the next statement on the pool after each.
- MySQL text that is not valid UTF-8 reads as U+FFFD for each bad sequence, as mysql2 reads
  it. Bytes bound on the prepared path and selected back (`SELECT ? AS b`) come back as text
  in the connection's character set, and asyncmy's strict decoding failed the statement (and,
  before the fix above, broke the connection).
- The DevTools client sends a batch holding a value with no JSON form of its own. A span
  attribute that was an exception without `to_json` (or any other such object) stopped the
  whole batch from being sent; each attribute value is now written as Effect's
  `JSON.stringify` writes it, an object as its instance fields (`{}` for a plain exception),
  and a value it would throw for (one that holds itself) as its `str`. An OTLP list attribute
  that holds itself is written as its text, where it overflowed the stack and lost its batch.
  `tests/test_exporter_hostile_values.py` runs every exporter over such values.
- An `HttpApiGroup` subclass without an identifier (`class Sub(Admin)`) serves the endpoints
  declared in its body, behind the middleware its group declares, as pyright types them; they
  were left out, so the client methods pyright gave them had no route. A group without an
  identifier that derives from two groups (`class Mixed(Public, Admin)`, which pyright
  refuses) is a `TypeError` where it served only the first group's endpoints. The declared
  middleware is read along the class's MRO instead of an inherited `__orig_bases__`.
  `tests/test_http_api_group_middleware.py` checks that every group class serves each endpoint
  attribute it has.
- The MCP stdio server stops at a line past 16 MiB, as Effect's NDJSON-RPC framing does; it
  held a line without a break however long it grew.
- The docstrings of `socket.ws.web_socket_constructor`, `layer_web_socket_constructor` and
  `socket.server` give the default message size limit, 100 MiB; they said 16 MiB.
- A MySQL connection is checked at connect for the two asyncmy internals the driver uses
  (`_encoding` and `_next_seq_id`), and an asyncmy without them fails there with
  `UnsupportedAsyncmyError` naming its version, where it would have failed later or read
  results wrongly; `tests/test_mysql_asyncmy_internals.py` pins both against the installed
  asyncmy. A statement failing after a multiple of 256 packets of its result counted as never
  sent (asyncmy's sequence id wraps to 0, the value the driver marked unsent), so its
  connection went back to the pool out of step; the driver marks an unsent command with -1.
- The SQL `PersistedQueue` store compares element ids and queue names exactly on MySQL and
  SQL Server, as the memory, Redis, SQLite and PostgreSQL stores do (GitHub issue #1). The
  tables kept the server's default collation, which on MySQL ignores case and accents (and
  on `PAD SPACE` collations trailing spaces) and on SQL Server ignores case and trailing
  spaces, so an offer whose id differed from a stored one only in those was dropped as a
  duplicate, and a queue's poller claimed the elements of a queue whose name differed only
  in them. A new migration (`0003_exact_ids`, run by `make_store_sql` / `layer_store_sql` on
  start, existing rows kept) makes both columns `VARBINARY` on MySQL and
  `Latin1_General_100_BIN2` on SQL Server, where the unique index and every comparison also
  count their lengths. `tests/oracle/test_sql_exact_key_columns.py` builds every pyfect SQL
  schema on both servers and fails if a key column compares inexactly.
- Security: `sql_event_log_server_encrypted` compares session auth public keys exactly on
  MySQL and SQL Server (GitHub issue #1). The bindings table kept the server's default
  collation, so a client could present a public key differing from another client's only in
  case, accents (MySQL) or trailing spaces, and the server took the other client's binding
  for its own: a client that bound such a variant first locked the real key's owner out,
  whose sessions were then checked against the wrong signing key. Stores stay separate (they
  are keyed by a hash of the exact key), so no entries could be read across keys. Apps running the encrypted event log server on MySQL or
  SQL Server should upgrade. `public_key` is now in `utf8mb4_0900_bin` on MySQL and in
  `Latin1_General_100_BIN2` on SQL Server, with its `DATALENGTH` in the primary key and the
  lookup; an existing bindings table is converted in place when the storage starts, rows
  kept.
- `sql_event_log_server_unencrypted` compares store ids, events, primary keys and session
  auth public keys exactly on MySQL (GitHub issue #1). In the server's default collation,
  entries written to store `Alice` were numbered and read with store `alice`'s, a batch
  lookup returned entries of a primary key or event differing only in case, accents or
  trailing spaces, and public keys differing only in those shared one binding. The columns
  are now in `utf8mb4_0900_bin` (values stay text, so Effect's storages can share the
  tables); existing tables are converted in place when the storage starts, rows kept.
- The SQL cluster storages (`sql_message_storage`, `sql_runner_storage`) compare entity ids,
  entity types, primary keys, shard ids and runner addresses exactly on MySQL and SQL Server,
  as on SQLite and PostgreSQL (GitHub issue #1). In the server's default collation a request
  to entity `alice` was dropped as a duplicate of one to `Alice` (or `alice `), clearing one
  entity's messages deleted the other's, a runner polling shard group `Alpha` claimed and
  reset group `alpha`'s messages, and two runners whose addresses differed only in case
  shared one registration and one set of shard leases. New migrations (message storage
  `0004_exact_keys`, runner storage `0002_exact_keys`, run on start, existing rows kept) put
  the columns in `utf8mb4_0900_bin` on MySQL (values stay text, so Effect's runners can share
  the tables) and in `NVARCHAR` with `Latin1_General_100_BIN2` on SQL Server, where the
  `message_id` unique index and every entity and primary-key comparison also count lengths.
  MySQL's advisory locks ignore case in lock names, so shards whose lock names differ only
  in case now get names of their own (the others keep Effect's). The SQL Server shard lease
  statement, which no SQL Server could parse, is fixed.
- A child process's exit is seen only once its `stdin` is destroyed, as in Node, which
  destroys `stdin` before it emits `'exit'`: a write made after `exit_code` (or
  `is_running`, or `kill`) reports the exit fails with `Premature close`, as Effect's does.
  The exit destroyed `stdin` in a later scheduler task, so a fiber that read `exit_code`
  before that task ran could still write to the pipe while a grandchild held it open
  (64 of 64 writes under load). Every read of a child's exit now runs its exit handler
  first, and `tests/test_process.py` checks each way a child ends and each way its exit
  is read. Found by dogfooding.

### Performance

- The RPC NDJSON parser, the ClickHouse row splitter, the CSV parser, the `schema_binary`
  frame parser and the multipart header parser take time linear in their input however a
  peer chunks it. Each searched its whole buffered line again, or copied it, for every chunk,
  so one long line sent a few bytes at a time cost quadratic CPU (a 1 MiB RPC line in 16-byte
  frames took 1.5 s, a 16 MiB one minutes), as Effect's RPC parser still does. `split_lines`
  and `split_lines_within` search a chunk of many lines once, where they searched it again
  for each line (4 Mi line breaks in one chunk took 12 s). `tests/test_splitter_linear_time.py`
  feeds every line and frame splitter a long line in small chunks and many lines in one
  chunk, and fails one whose time grows faster than its input.

### Docs

- The streams guide lists every framing decoder's limit and default under "Input from a
  peer", and says that input from a peer you do not control needs one. The HTTP server's
  security defaults name the 16 KiB request head limit, the chunk and trailer limits, the
  100 MiB WebSocket message limit and the multipart `MaxFieldSize`, `MaxFileSize` and
  `MaxParts`.
- The HttpApi guide gives `StreamNdjson`'s 1 MiB `max_element_bytes` line limit and its unset
  `max_bytes`, and the RPC guide the 16 MiB `max_buffer_size` of NDJSON framing and how to
  change it.

## 0.6.3 (2026-11-13)

### Fixed

- `RpcGroupWith[M]` wraps every procedure of the group in `M`, as Effect's
  `RpcGroup.middleware` does: those it inherits from merged groups
  (`class Api(Public, RpcGroupWith[M])`) and those declared in its subclasses. They were
  served without the group middleware, on the server and the client, while pyright typed
  them as wrapped, so an app relying on a group middleware for authentication left those
  procedures open: upgrade. `Group.rpcs` is now the one source of a group's procedures, with
  the middleware applied, and each RPC attribute of a group class reads it, so the procedure a
  handler is given for is the one served. `RpcGroupWith[A | B]` wraps in `A` then `B` (a
  union was kept as one invalid middleware), and a group that is two different
  `RpcGroupWith`s, which pyright refuses, is a `TypeError`.
- `json_patch.get` gives `[]` for two NaN floats that are different objects (`inf - inf` and
  `inf * 0`), as Effect's `Object.is` does; it gave a `replace`. Numbers are compared by
  `pyfect._js.same_json_value`, and `tests/test_object_is_guard.py` keeps hand-written sign
  comparisons out of every other module. Found by dogfooding (stockroom).
- `json_patch.apply` raises `TypeError` for a value that is not a patch, as Effect's does: an
  operation that is not an object, has no string `path`, or is an `add` or `replace` without a
  `value`. It raised `KeyError` for some of these. An operation with no `op` is a `replace`,
  as in Effect, where it raised `KeyError`. Found by dogfooding (stockroom).
- `TxHashMap.from_iterable`, `HashMap.from_iterable`, `MutableHashMap.from_iterable` and
  `Trie.from_iterable` of a list of pairs infer `str` and `int`, as `make` does, where pyright
  kept the literals (`TxHashMap[Literal["a"], Literal[1]]` for `[("a", 1)]`), so a later
  `set("b", 2)` was a type error. `tests/test_pair_literals_guard.py` makes every overloaded
  `Iterable[tuple[K, V]]` parameter come with the `list` overload that widens them. Found by
  dogfooding (stockroom).
- The live server's WebSockets answer pings and the client's close while the handler is not
  pulling, as `ws` does under Node: the connection is read on until 64 KiB of messages wait
  (Effect's high-water mark). A handler that only wrote left the client waiting for the close
  reply, and the connection open, until the client gave up, so the handler ran on and server
  shutdown waited for it. Once both sides have ended, the connection closes (after `ws`'s 30
  second `closeTimeout` if the client never ends its side), and the handler is interrupted as
  a client abort. Found by dogfooding (stockroom).
- `uvicorn_server` no longer trusts `X-Forwarded-For` and `X-Forwarded-Proto`: it sets
  uvicorn's `proxy_headers` to `False`, so a request's `remote_address`, `peer_address` and URL
  scheme are the socket's, as with `live_server`, `hypercorn_server` and Effect's Node server.
  uvicorn's default took them from any peer in `FORWARDED_ALLOW_IPS` (loopback unless set),
  ahead of the app's own `x_forwarded_headers`. To trust a proxy, use `x_forwarded_headers`
  with its addresses, or opt back in to uvicorn's handling with
  `uvicorn_server.layer(config={"proxy_headers": True, "forwarded_allow_ips": ...})`.
  `tests/test_server_transport_peer.py` checks every server adapter.
- A client TLS upgrade (`reader.upgrade`) on a `make_net` socket without a `servername`
  checks the server certificate against the host it connected to, as Node's `tls.connect`
  under Effect's `NodeSocket` does and as `make_tls` already did. It checked `localhost`, so a
  certificate issued for `localhost` was accepted for any host. For an IP literal, a Unix or an
  adopted socket the name is still `localhost`, as in Node. The side a socket upgrades as (a
  server, or a client with its host) is now required where sockets are built, so a new kind of
  socket cannot leave it out.
- `console_json`, `format_json`, OpenTelemetry span events, log records and attributes, the
  OTLP exporters and the DevTools client hide what `CurrentRedactedNames` names in `Headers`,
  `UrlParams`, requests, responses and HTTP client errors, as `console_pretty` and
  `console_logfmt` did for errors. Their JSON walked a value's entries, fields or exception
  attributes before its own `to_json`, so logging an HTTP error or request (for example with
  `catch_all(log_error)`) wrote authorization, cookie and URL signature values, and the
  underlying httpx request, as they were. As in Effect's `formatJson` and `format`, a value's
  redacted form (`Redactable`, here `__redacted__`) and then its own `to_json` come first,
  wherever it is nested; `pyfect._json_text.stringify` writes a value's `to_json` before its
  mapping entries too, as `JSON.stringify` calls `toJSON`. `pretty` and `logfmt` now also redact
  `Headers` and `UrlParams` logged directly. `tests/test_log_redaction.py` logs each redacting
  type through every logger and exporter, and `tests/test_log_redaction_guard.py` keeps sinks
  from walking values themselves and every type that redacts giving its redacted form.
- Security: ClickHouse names could end their quotes early. A name given to `sql.identifier`,
  a key of a record given to `sql.insert` or `sql.update`, or the column of `sql.in_` was
  quoted by doubling `"` only, but ClickHouse reads a backslash in a quoted name as an escape,
  so a name holding a backslash could close the quotes and the rest of it ran as SQL.
  Backslashes are now doubled too. Effect's ClickHouse client quotes names the same unsafe way;
  pyfect deliberately differs here. Apps that pass user input as names on ClickHouse should
  upgrade.
- Security: MySQL values written into the statement text could end their literal early when the
  session's `sql_mode` has `NO_BACKSLASH_ESCAPES`. That covers `.stream`, `.unprepared` and every
  statement under `disable_prepared_statements=True`. Text was written for the session's mode
  only for a top-level `str`: `bytes`, the items of a `tuple`, and values of other types
  written as text (a `UUID`, an enum, any object) were always backslash-escaped, which that
  mode reads as plain text, so the rest of the value ran as SQL. Every value holding text is now
  written for the session's mode, and bytes as `X'hex'`, as mysql2 writes a Buffer. Apps that
  bind user input on these paths against a server in that mode should upgrade.
- `tests/oracle/test_sql_hostile_round_trip.py` round-trips generated names and values full of
  quotes, backslashes, comment markers, NUL and other Unicode through `sql.identifier`,
  `sql.insert` / `sql.update` keys, `sql.in_` and every binding path (prepared, unprepared,
  stream) on a real server of each dialect (PostgreSQL, MySQL in each of its quoting modes, SQL
  Server, SQLite, libSQL, ClickHouse, and D1 on its SQLite stand-in), and asserts each comes back
  unchanged with no other column or row.

### Docs

- A request batching page: requests and resolvers, why requests batch only when made
  concurrently, failures (`entry.fail`, a failing run, `UncompletedRequestError`), shaping
  batches (`batch_n`, `grouped`, `set_delay`, `from_function_batched`, ...) and `with_cache`.
- Observability has a section on error reporting (`with_error_reporting`,
  `error_reporter.make` / `layer`, `report_ignored` / `report_severity` / `report_attributes`);
  `RcRef` and `FiberHandle` have examples in Resources and Concurrency.
- Transactions shows `TxHashSet` and `TxChunk`, `TxDeferred`, `TxSemaphore` and
  `TxReentrantLock` coordinating fibers, and `TxPubSub` and `TxSubscriptionRef`. A new section
  says that a failure caught inside `tx` keeps the writes made before it (there are no
  savepoints), as in Effect.
- optics.mdx says what `json_patch.apply` does not check, as Effect's does not: an `op` other
  than `add` or `remove` is a `replace` (so a `test` overwrites the value it should check),
  and a value that is not a patch raises `TypeError`; decode a client's patch with a schema
  first.
- schema.mdx says that `S.to_codec_json(...)` encodes to `JsonValue`, as Effect's is typed
  `Json`, and that arrays encode as their schema's container (`tuple` for `S.Array`, `list`
  for `S.List`).
- http-server.mdx says how a WebSocket is read while the handler does not pull, what happens
  to the handler when the client leaves, and how to end a handler that only writes. PARITY §4
  records the Effect bug not copied: under Node, `ws` keeps Effect from interrupting the
  handler when its client leaves.

## 0.6.2 (2026-11-13)

### Deprecated

- `pyfect.socket.ws.make_server` and `layer_server` warn; use
  `pyfect.socket.server.make_web_socket` and `layer_web_socket`. They are removed in 0.7.0.
- The `intl` extra installs nothing: `date_time.intl` ships its data (ICU's CLDR data, under the
  Unicode License v3, beside it as `LICENSE`) and needs no babel. The extra stays so
  `pyfect-dev[intl]` still installs.

### Added

- An `audit` workflow checks `uv.lock` and `website/bun.lock` against known vulnerabilities
  (OSV) on every push and weekly, and `tests/test_workflow_security.py` keeps every
  workflow's actions pinned to commits, read-only by default, off `pull_request_target`, and
  free of pull-request text in its scripts.
- `pyfect.socket.server.make_web_socket` and `layer_web_socket`, Effect's
  `NodeSocketServer.makeWebSocket` and `layerWebSocket`, where Effect has them: a
  `SocketServer` whose connections are WebSockets (on the `websockets` extra), such as a
  DevTools server for the default `devtools.layer()` client. Handlers get the upgrade request
  as the new `IncomingMessage` service, as well as the native socket as `WebSocket`. The
  server existed only as `pyfect.socket.ws.make_server` / `layer_server`, where a dogfood app
  looking for Effect's names did not find it; a test now checks that every `NodeSocketServer`
  export is in `pyfect.socket.server`. Found by dogfooding (lantern).
- A differential tester of the runtime against Effect 4.1.2 (`tests/runtime_diff`). Hypothesis
  generates programs in a small language (succeed, fail, die, flat maps and catches; forks,
  joins, interrupts, races and timeouts; resources, scopes and finalizers; sleeps on the test
  clock, concurrency-limited `for_each`, retries and repeats on schedules; queue, deferred and
  semaphore handoffs; stream pipelines), each step logging an event. Each program runs in
  pyfect and, under Node, in Effect, and the two must agree on the exit, the shape of its cause
  and the order of every event. A checked-in corpus of 506 programs with Effect's answers
  replays in every pytest run without Node; `python -m runtime_diff` (from `tests/`) grows or
  refreshes it and surveys fresh programs. The `fuzz` workflow compares 300 fresh programs
  with Node on every push and 20,000 weekly.
- A soak test (`tests/soak`, `python -m soak run` from `tests/`): HTTPS and WSS traffic
  through the live server and the httpx client (keep-alive, streamed bodies, WebSockets),
  fiber, scope, pool, cache, queue, PubSub, semaphore, stream, retry, schema and SQLite
  workloads, with failures, timeouts and interruptions on purpose, at a moderate pace for
  hours. It samples memory, objects by type, live fibers, file descriptors, threads and
  each workload's latency into a JSONL file, and `python -m soak analyse` fails when,
  after the warm-up, any of them trends upward (a robust slope over bin floors, so noise
  and the collector's sawtooth pass), latency rises, a workload stalls or fails
  unexpectedly, or the shutdown leaves fibers running. The `soak` workflow runs it for
  over five hours weekly and on demand on 3.13, 3.14 and free-threaded 3.14t.

### Fixed

- Shared-state types shared by runs on different threads (`fx.run_blocking` from a thread pool,
  `ThreadWorker`s, a `ManagedRuntime` per thread) lost updates, handed out items twice and left
  waiters asleep. Each operation counted on one fiber step being atomic, which holds for one
  run's fibers but not for runs on other threads, on 3.14t or with the GIL. Eight threads
  making 10,000 runs each of `fx.tx(ref.update(+1))` on one `TxRef` ended near 69,000 of 80,000
  on 3.14t (two transactions checked the same version and both committed; a `TxHashMap` of
  stock sold 106 items it did not have), and `Ref.update` lost updates the same way. Now each
  primitive holds a lock of its own while it reads and changes its state, and lets it go to
  resume a fiber; transactions check and commit under one process-wide lock. Effect's deferred
  wake-ups (a queue's taker, a semaphore's waiter, a latch's) were queued on the waking run,
  which never ran them once its root fiber ended, so a waiter in another run slept forever;
  they now go through the waiter's own run. `tests/cross_run` shares every such type between
  eight threads' runs on both builds (the free-threaded CI job runs it too), forces the `Ref`
  and wake-up races to happen every time, and fails when a public class whose effects change
  its own state has no case there. Docs: [Threads](/docs/threads#sharing-state-between-runs)
  states the contract. Found by dogfooding (stockroom).
  What went wrong where, before (both builds unless noted):
  - `Ref` read-modify-writes lost updates, `get_and_set` handed a value back twice (3.14t).
    The update function now runs once, holding the ref's lock.
  - `TxRef` lost commits, transfers between two refs changed their sum, a `tx_retry` waiter
    missed a commit from another run, and so every `Tx*` collection broke: `TxHashMap` sold
    more than its stock, `TxQueue` and `TxPriorityQueue` handed items out twice, `TxSemaphore`
    and `TxReentrantLock` let holders overlap, `TxDeferred` completed twice.
  - `Semaphore`, `SynchronizedRef`, `SubscriptionRef`, `Latch`, `Queue` (bounded, unbounded,
    rendezvous), `PubSub` (every strategy, and with replay) and `PartitionedSemaphore` hung on
    lost wake-ups and let holders overlap; `Deferred` lost a waiter on 3.14t.
  - `Pool` hung, also because its resize fiber was forked on the borrower's short run; it now
    forks on the run that made the pool. `Cache`, `ScopedCache`, `fx.cached` and a resolver's
    `with_cache` ran a lookup twice or raised `KeyError`. `RcRef` and `RcMap` used a released
    resource or hung on an idle time to live, whose timer ran on the releasing caller's run;
    it now runs on the run that made them.
  - `FiberMap` and `FiberHandle` lost a fiber set from two runs at once, `FiberSet` missed an
    add racing its close, a scope lost finalizers and forks added while it closed (or raised
    "dictionary changed size"), and an observer added to a fiber finishing on another thread
    was never called.
  - Metrics lost increments (counters, gauges, frequencies, histograms, summaries), two runs
    could get different `Reference` defaults (and so two metric registries),
    `MutableHashMap.modify` lost updates, a shared `SnowflakeGenerator` handed out the same
    snowflake twice and `MemoryRateLimiterStore` lost tokens.
- `EventLogService.synced` (a pyfect addition) no longer waits forever when a remote
  acknowledges this log's upload before the entry before it has been replayed. The remote
  leaves a connection's own writes out of its change stream and the journal's cursor crosses
  only acks that continue straight on from it (both as in Effect), so the cursor stopped
  short of the server's latest sequence. `synced` now counts the sequences the remote
  acknowledged for this log's uploads as seen, on top of the cursor, which every journal
  still reports as Effect's does. Once `destroy` has run on the log, `synced` fails with the
  new `EventLogDestroyedError` (exported from `pyfect.eventlog.event_log`) instead of
  counting the acks of destroyed entries or waiting for a change stream that does not start
  again; a journal destroyed directly, not through the log, is not noticed. `synced`'s error
  type gains `EventLogDestroyedError`, so code that handles its errors exhaustively must add
  it. A property test commits acks and replays in every order on
  the memory and SQL journals and checks `synced` sees the end, and never a sequence the log
  lacks. Found by dogfooding (quill).
- `S.Finite` and `S.is_finite` read an `int` as a JavaScript number, so one past the largest
  double (a 400-digit JSON literal, which `JSON.parse` reads as `Infinity`) is not finite, as
  in Effect. `jwt.verify` checks `exp`, `nbf` and `iat` with `S.Finite`, so a token signed
  with such an `exp` verified as never expiring, where Effect fails it with
  `ClaimValidationFailed("exp", "invalid")`. Found by the security review
  (`docs/security-review-2026-11.md`).
- The httpx client keeps no cookies of its own. httpx's jar stored every `Set-Cookie` and sent
  it with later requests to that site, so a server sharing one `HttpClient` between users sent
  one user's session cookie on another user's calls. Effect's fetch client keeps none either;
  cookies persist only through `with_cookies_ref`. Found by the security review.
- `live_server` searches each received byte of a request head, chunk-size line or trailer
  once. Every arrival searched the whole buffered head again, so a client sending a 16 KiB
  head one byte per packet cost the event loop about a second of CPU, and a few such
  connections slowed every other request. Found by the security review; Node's llhttp parses
  incrementally too.
- Generated schema decoders (`jit_compiler`, `aot_compiler`) write a literal as source only
  when it is exactly a `bool`, `int`, `str` or `float`. A subclass's `repr` was pasted into
  the code the compiler runs, so a `str` subclass with its own `__repr__` ran that text, and
  an `IntEnum` literal gave source that did not compile (the schema fell back to
  interpreting). Found by the security review.
- A process started by a `pyfect.workers` worker no longer takes the worker's channel
  variable for its own. The parent now passes its pid with the channel's descriptor, and a
  process whose parent is another ignores the channel instead of unpickling whatever its
  descriptor of that number is. Found by the security review.
- `uvicorn_server` and `hypercorn_server` hold a request that arrives before an app is served
  until it is, as Effect's `NodeHttpServer` leaves such a request pending; it used to get an
  empty 503. The socket is bound when the server's layer is built, before the layers of the
  app it serves, so a client that waited for the port got a 503 while a slow layer (telemetry,
  a database pool) was still starting. A WebSocket upgrade waits the same way instead of
  closing with 1013. The test runs on every server built on the shared ASGI listener, and
  fails if a new one is not added to it. When the server closes without an app ever having
  been served, the requests still waiting get an empty 503 at once (Node's `server.close`
  would wait for them for ever); closing used to take the engine's graceful timeout (about
  20 s on uvicorn, longer on hypercorn) and log a cancelled task's traceback. Found by
  dogfooding (lantern).
- `S.Struct` of a parameterized generic TypedDict (`S.Struct(Body[Inner])`) has the TypedDict's
  keys with the type arguments in place, also as another key's annotation and in
  `S.TaggedStruct`. `get_type_hints` of the alias is empty, so the struct had no keys at all
  (it accepted anything), and giving a key its own schema raised
  `TypeError: Body has no key 'body'`. Every reader of a TypedDict's annotations now goes
  through one function that substitutes the arguments, and a test fails on any other
  `get_type_hints` call in `pyfect.schema`. Found by dogfooding (lantern).
- A WebSocket server connection that its client closed before a handler read it no longer
  loses the messages sent before the close. A paused `WsWebSocket` stopped waiting once the
  connection closed and delivered the messages it held to no listener; it now reads nothing
  while paused, as a paused `ws` socket in Effect, until it is resumed or closed on this side.
  So a short-lived app that reported its spans to a DevTools server and exited before the
  server's `run` took the connection lost them all. Found while porting the DevTools docs.
- Each fiber queues its tasks in its own dispatcher, as Effect's default scheduler does
  (`fiber.currentDispatcher`): the children it forks without starting them, its yields and the
  wakes it makes (queues, semaphores, latches, pools, transactions) run together in one task,
  so a task joins its fiber's pending batch ahead of tasks other fibers queued since. All of a
  run's tasks used to wait in one queue, so forks, yields and wakes could run in a different
  order than in Effect. `yield_now_with` priorities order tasks within one fiber's batch, as in
  Effect, not across fibers. A test fails if runtime code queues a task on the run's scheduler
  directly instead of on a fiber's dispatcher. Found by the runtime differential tester.
- `for_each` with `concurrency="unbounded"` (or any limit above 1) over a single item forks it,
  as Effect does; it used to run it in place, so the item's own interruption stayed in the
  cause. Concurrency is resolved once, as Effect's `resolveConcurrency`. Found by the runtime
  differential tester.
- `date_time.intl` prints what Effect's `DateTime.format`, `formatUtc` and `formatLocal` print
  under Node, across locales, options and zones. It was built on babel, which has other CLDR data
  and another pattern engine, and differed from Node in about half of 33,000 cases: Latin digits
  where a locale has its own (`ar-EG`, `bn`, `fa`, `mr`), zone names such as `+0100` and `TU`
  where `Intl` writes `GMT+1` and `UTC`, a long date and time joined with `, ` where `Intl` writes
  `at`, field combinations joined without their separators, hours padded otherwise, Gregorian
  dates for locales whose calendar is Buddhist or Persian (`th-TH`, `fa-IR`), no metazone history
  (1969 in New York is `GMT-04:00`, not Eastern Daylight Time), and locales babel lacks raising.
  It now ports V8's option handling, ICU's pattern generator, date formatter and zone names, and
  the Gregorian, Buddhist and Persian calendars, and reads the data ICU 78.3 ships (CLDR 48.0, as
  Node 24.22.1 has it, with ICU's metazones for tz 2026e). Also as `Intl`: a style mixed with a
  field option is a `TypeError`; a malformed locale is a `ValueError` with V8's message; with no
  locale, or one ICU lacks, the locale is the environment's (`LC_ALL`, `LC_MESSAGES`, `LANG`);
  `format_local` uses the system's named zone; Irish summer time is daylight time, as in ICU, also
  where the system's tz data writes Irish winter time as a negative save (Linux); and `format_utc`
  is UTC even with a `time_zone`, as Effect's `formatUtc` puts UTC over it. A `-u-ca-` calendar
  other than those three raises `ValueError`. The 59 cases a dogfood app found were a sample; the
  only comparison with Node before was a 90-case matrix over five locales, run once and never
  kept. `tests/oracle/test_intl_differential.py` now replays 33,338 of Node's answers
  (`intl_answers.json`, regenerated by `scripts/gen_intl_answers.py`) on every run, fails on any
  case that differs except the named known differences, and fails if the data and the answers come
  from different Node versions.
- An interrupted sleep, and a timeout that did not fire, no longer leave their timer in
  memory until its deadline. Cancelling a timer of `run_blocking`'s scheduler (or of the
  `TestClock`) only flagged it, so the timer and what it would have run stayed in the heap:
  with a 60-second timeout around each operation the soak test held about 14,000 dead
  timers, and a long timeout on every request of a busy server holds rate x timeout of
  them. A cancelled timer now lets go of its task at once and cancelled timers are swept
  out once they are most of the heap, as asyncio does and as Effect's `clearTimeout`
  frees its callback. Every timer heap is now one `TimerHeap`, and a test keeps it so.
- The httpx client frees the response to a streamed upload once the program is done with
  it. Each response's abort was kept in a module-wide weak-keyed table whose entry reached
  its own key again (through the upload body's abort listener, the request's context and
  its span), so the entry, the response and its connection objects were never freed:
  eight responses a second under the soak's load. The finalizer that aborts a response
  dropped unread held the same chain, so for a streamed upload it never ran and the
  response stayed. The abort is now an attribute of the response, the upload body's abort
  listener is removed once the body is sent, and a test keeps weak-keyed tables out of
  `pyfect.http`.
- The httpx client closes the connection of a request interrupted during its TLS
  handshake. httpcore (1.0.9) closes the stream when a handshake fails but not when it
  is cancelled, so every request a timeout cut off while connecting left its socket
  open, on both ends, for good: the soak test's open file descriptors rose by about one
  a minute. The client now gives its connection pools a network backend that closes the
  stream whatever ends the handshake.
- The httpx client closes the connection of a request interrupted at any other point
  too. Three more cancels left an HTTP/1.1 connection open with nothing to close it: one
  landing as anyio (4.15.1) finished connecting (its socket was never handed on), one
  between connecting and the request starting (the connection stayed `NEW` in the pool,
  never reused and never expired, so a pool of them made every request wait), and one
  while the response released its connection (it stayed `ACTIVE`). The client now
  connects where a cancel cannot reach and closes what such a connect opened, and closes
  a pooled connection its failed request left `NEW` or its closed response left
  `ACTIVE`. A test cancels a request at every event-loop turn of its life and checks
  nothing is left open.
- The live server closes a connection whose TLS handshake does not finish. A client
  that hung up during the handshake left the server's side open (the end of input did
  not fail the handshake), and a client that never sent one held its connection for
  good. Now the end of input fails it, and `make_tls` drops a handshake that takes
  longer than `handshake_timeout` (Node's `handshakeTimeout`, 120 seconds).
- `S.Struct` of a recursive TypedDict made at run time (per tenant or plugin) no longer
  keeps the class alive forever: its cached schema reached the class through the
  recursive reference. The reference now waits on the schema, not the class.
- `openapi.from_api` with option functions no longer keeps a document per call when the
  functions are made fresh on each call, nor the API when a function reaches it. Its cache
  is weak at every level, as Effect's is (on the options, then on the API). Every
  weak-keyed table and `weakref.finalize` in pyfect is now listed with what makes it free
  (`tests/test_weak_tables.py`), so a new one is checked before it lands.
- `S.UnknownFromJsonString`, `S.from_json_string` and the `stringify_json` getter write `NaN`
  and infinities as `null`, as Effect's `JSON.stringify` does. A JSON number past the largest
  double (`1e400`, `555555555E555555555555`) decodes to an infinity, in Effect too, but encoding
  it failed with "Expected a JSON-serializable value", so decode accepted what encode
  rejected; `S.encode_unknown_sync(S.UnknownFromJsonString)(decoded)` of `[1e400]` is now
  `"[null]"`. The fuzz differential now compares `UnknownFromJsonString`'s decode and encode
  with Effect's on the `schema_json` corpus. Found by the `schema_json` fuzz target.

### Performance

- Forking and yielding cost what they did in 0.6.1 again. The per-fiber dispatchers added in
  this release made `benchmarks/streams.py`'s fork-heavy case 30 to 37% slower: each fiber
  allocated a dispatcher and a batch, and each task went through a thread check and an extra
  scheduling hop. A fiber now keeps its batch in its own slots, a batch of one task allocates
  nothing (a yield is held as is), and the fiber's own yields, forks and wakes queue without
  the thread check; Effect's ordering is unchanged. A queue asks for its waker only when it
  wakes a taker, and the scheduler checks for due timers with one comparison per turn, as it
  did before the soak's `TimerHeap`. On CI, alternating on one runner: fork-heavy x0.90 to
  x0.98 of 0.6.1 (x0.57 to x0.66 of the release branch before this), queue offer/take x1.02
  to x1.07, map + filter unchanged.
- `benchmarks/compare.py` compares a commit with its branch base (the merge base with
  `origin/main`, or the first parent on `main`), alternating the two on one machine, and CI
  runs it after the gate: fork-heavy and queue fail beyond x1.10 of the base, set from twelve
  CI runners comparing a commit with itself (x0.93 to x1.04), and the other cases beyond
  x1.25. The gate's x1.6
  against a fixed baseline had let the x1.37 through, as runners differ by that much.

### Docs

- `SECURITY.md` names the supported release, response times and scope, with a placeholder
  for a security contact address, and links the November 2026 security review
  (`docs/security-review-2026-11.md`), a manual audit of the code that handles untrusted
  input or secrets.
- http-server.mdx says when the server starts answering: its port opens before the app's
  layers are built, and requests wait for the app meanwhile, so readiness checks should
  request a route.
- postgres.mdx: streaming a statement's rows with `.stream` (a query ended early is cancelled),
  `timestamptz` values arriving in the session's time zone and decoded with
  `S.DateTimeUtcFromDate` as Effect decodes a `Date`, reading the name of the constraint a
  `ConstraintError` broke from the driver's cause, and where the spans' `db.namespace` and
  `server.address` come from (the config's `database` and `host`, not `url`, as in Effect).
- A DevTools page: the client layers, what the protocol carries, and serving the DevTools side
  on `socket.server.layer_web_socket`.
- PARITY §4 records an Effect bug not copied: a fiber that ends while interrupted waits for a
  child that ignores interrupts interruptibly, so its exit becomes the bare interruption and a
  finalizer's defect is lost. pyfect keeps the exit.
- The schedules guide has a section on formatting dates: the options, the ICU and CLDR versions
  the text follows, and the one known difference.

## 0.6.1 (2026-11-12)

### Added

- Fuzzing of every parser of untrusted input (`tests/fuzz`): 32 targets covering the HTTP/1
  server (request heads, chunked and compressed bodies, multipart, URLs, cookies, WebSocket
  frames and extensions, and the live server end to end), the JSON family, CSV, NDJSON, SSE,
  XML, TOML, YAML, INI, tar, zip, schema decoding of JSON and binary input, JOSE and key
  formats, durations, date-times, cron, dotenv and Config. Each target allows only its
  documented errors and runs under a time limit. A checked-in seed corpus replays in every
  pytest run, along with a short Hypothesis fuzz of each target and a comparison with Effect's
  answers (`effect_answers.json`, from Effect under Node) on every parser the two share,
  so a divergence the fuzzers find stays fixed. The
  `fuzz` workflow runs Atheris on each target for 30 seconds on every push, and for 20 minutes
  weekly or on demand, uploading any crash. `python -m fuzz` (from `tests/`) runs targets
  locally and `--differential` compares a grown corpus with Effect.

### Fixed

- `channel.scoped` rejects an argument that is not a channel when it is called, naming the
  parameter, as every other channel function does; it used to fail only once the channel ran.
  The argument guard test skipped parameters typed `ChannelBase`, which is how it slipped
  through; it checks them now. Found by mutation testing.
- A schema parsed with `concurrency` reports a defect or issue from a child that fails after the
  parse was already decided, as Effect's concurrent parse does; such a child used to leak an
  internal exception into the result, a `SchemaError` that crashed when formatted. No child
  starts once the parse is decided. Found by mutation testing.
- `Cause.pretty` keeps an unraised error's message exactly, as Effect does; trailing whitespace
  was stripped (`ValueError("boom  ")` printed as `ValueError: boom`). Found by mutation testing.
- `date_time.add` and `subtract` keep a far year's microseconds exactly: the result was
  rebuilt through a float of epoch milliseconds, so adding nothing to
  `2249-01-01T00:00:00.000001` gave `.000002`. Found by a new property test; a guard now
  rejects a float between an instant and a `timedelta` anywhere in `pyfect.date_time`.
- `S.to_strategy` of the network refinements (`MacBroadcastAddress`, `Ipv4PrivateAddress`,
  `IpLoopbackAddressFromString` and the rest) draws only addresses they accept. Their own
  strategy sat on the refinement's check, where derivation never read it, so they filtered
  plain addresses for the few that pass (one in five for `MacBroadcastAddress`) and Hypothesis
  sometimes gave up on a test with "filters out too many inputs". A test now measures, without
  randomness, that every exported schema's strategy keeps at least half of what it draws, and
  that no check carries a `to_arbitrary`.
- `race`, `race_first`, `race_all`, `race_all_first` and `timeout` no longer return before their
  losers have stopped when an interrupt lands just after the winner decided the race. The losers
  were stopped in the effect the winner resumed the race with, which a fiber that paused there
  for its step budget (`MaxOpsBeforeYield`) skipped once interrupted, so `timeout(...)` could
  return while the timed-out effect still held its resources. They are now stopped in an
  `on_exit` around the wait, however the race ends, as Effect's `raceAll` does with its
  `onExitUnsafe` hook. Found by the interleaving harness (`tests/interleave`), as were the next
  three; a new test bans handing work to a callback's `resume` anywhere in `src`.
- A pool no longer releases an item it has just put in service when its scope closes at that
  moment. The resize fiber published a new item while interruptible, so an interrupt in the
  pause right after (the pool's scope closing) made it close the item's scope while borrowers
  held it. Only the acquire is interruptible now; publishing the item is not. Effect's
  `Pool.ts` `allocate` restores interruptibility around both and has the same gap.
- A pool borrower woken to retry no longer parks forever next to free items. A woken waiter
  keeps its place in line; if its retry found nothing and items came back before it parked
  again, their wake-ups had skipped it (it was awake), and it then parked because the line, which
  held only itself, was not empty. It now goes on when nobody asleep is ahead of it. Effect's
  `waitForItem` checks `waiters.size === 0` and has the same race.
- A `ScopedCache` lookup whose last getter left while the lookup was in its uninterruptible
  acquire is released. The lookup went on to succeed into an entry already removed, and
  nothing closed its scope, not even closing the cache. The last getter now closes the entry's
  scope once the lookup has stopped. Effect's `ScopedCache.ts` has the same leak.
- `terminal.live` no longer reads its input after a reader stops. Interrupting `read_line`, or
  closing `read_input`'s scope (as every prompt does when it finishes), abandoned the read it
  had handed to a worker thread, which could still run afterwards and take input meant for the
  next reader of that descriptor (another terminal or `input()` on standard input) or, once the
  descriptor was closed, for whatever reused its number. A stopped reader now waits for that read, at most
  50 ms once it has started (on Windows, where a read cannot time out, it is still abandoned).
- Fuzzing (`tests/fuzz`, Atheris and Hypothesis, see Added) found these differences from Effect
  and inputs that raised where a documented error belongs (each has a regression input in
  the corpus and a test in `tests/fuzz/test_regressions.py`):
  - An `Origin` header holding an unclosed IPv6 literal (`http://[`) made the origin check of
    WebSocket upgrades and RPC calls die with a 500 (`urlsplit` raises `ValueError` there);
    `request_to_web` and the ASGI mount had the same raise. The origin is now no origin, so the
    check refuses it, and `request_to_web` fails with `RequestParseError`. Request-facing code
    splits URLs only through `_url_text.split_url`, which returns `None` where `urlsplit` raises
    (`tests/test_split_url_guard.py`).
  - Importing an SPKI or PKCS#8 key naming an algorithm `cryptography` does not know (an
    `UnsupportedAlgorithm`), or a PKCS#8 key of the wrong size for its algorithm (a 32-byte
    Ed448 key, which OpenSSL fails with an `InternalError`), was a defect, not a `CryptoError`
    `InvalidKey`. Keys are loaded
    only through `crypto._lib`'s loaders, which turn every unreadable key into `None`
    (`tests/test_crypto_key_loading_guard.py`).
  - TOML and YAML nested about 500 levels deep raised `RecursionError`. They now recurse
    through `with_fresh_stack`, as recursive schemas do, so they read input nested far deeper
    than JavaScript's stack allows; past that `toml.parse` fails with an `EncodingError` and
    `yaml.parse` raises `ValueError`, as Effect's do when their stack runs out.
    `tests/test_deep_nesting.py` feeds every nested-text parser 200,000 levels.
  - `ini.parse` documents the `TypeError` it raises for a property in a section named after a
    value (`a=1`, then `[a]`, then `b=2`), as Effect's `Ini.parse` throws; its docstring said
    `ValueError`.
  - `cron.parse`, `semver_range.parse` and the cookie parsers read whitespace as Python does,
    where Effect reads JavaScript's: U+001C to U+001F and U+0085 separated cron fields and range
    comparators and were trimmed from cookie names and values, and a byte-order mark did not
    separate them. They now split and trim as Effect does (`_js.split_space`, `_js.trim`), and
    `tests/test_js_whitespace_guard.py` fails on Python's whitespace methods or a regex `\s` in
    any module ported from one of Effect's text parsers.
  - `ini.parse` named a quoted key holding JSON by its Python `repr` (`'[]'` became `"[]"`);
    it is now `String(key)` as in Effect (`""`), and a key whose JSON has a `length` over 2
    raises Effect's `TypeError`.
  - `date_time.zone_from_string` documents that an offset of a day or more is `None`, as
    Python's `tzinfo` cannot hold one; Effect accepts up to `±99:59`.

### Docs

- The asyncio guide no longer says an open client connection holds a TLS server's shutdown;
  since 0.6.0 stopping closes idle keep-alive connections at once.
- The libsql guide says sqld can wedge with several concurrent writers (sqld's bug; Effect's
  driver hits it too), and that one writer at a time avoids it.
- `pyfect.trie` no longer says the empty string is never a key: it is one, first in order, as
  in Effect.

## 0.6.0 (2026-11-12)

### Changed

- The services that held their operations in dataclass fields of function or effect type are
  classes whose operations are documented methods and properties, as `MacService` has been
  since 0.5.3, so `help()`, `inspect.signature` and the API reference show them. Constructors
  keep their keywords, positional order and defaults, and `svc.op(...)` / `svc.value` read as
  before. Converted: the ai provider clients (`anthropic`, `openai`, `openai_compat`,
  `openrouter`, `cloudflare`, `typesafe`, the OpenAI socket), `IdGenerator`, `LanguageModel`'s
  hooks, the MCP client transport, `RunnerHealth`, `RunnerStorage`, the RPC client and server
  protocols, `RpcClientProtocol`, `RpcSerialization`, the RPC connection hooks,
  `WorkflowEngine`, `WorkerPlatform`, `WorkerRunnerPlatform`, `EventLogRemote`,
  `GraphQLProtocol`, `HttpPlatform`, `HttpServer`, the OTLP flusher and serialization, the
  `KeyValueStore`, `PersistedQueue` and `CircuitBreaker` stores, `BackingPersistence`,
  `UserDirectories`, `ChildProcessSpawner`, `Socket`, `DatagramSocket`, `Stdio` and `Terminal`.
  They are no longer dataclasses:
  - `dataclasses.replace(svc, op=...)` becomes `copy.replace(svc, op=...)`, which every one of
    them supports; `dataclasses.fields` and `asdict` no longer apply.
  - Two of them are equal only when they are the same object (as the crypto services), where
    a dataclass compared its fields; hashing is by identity too.
  - Their plain data attributes (such as `http_client` or `max_response_bytes`) can be
    assigned; the operations' properties are read-only.
  - `SqlClientService.reserve` and `PgClientService.pool_stats` are read-only properties:
    build a new client instead of assigning them.
- Each converted module also exports the errors its service's methods fail with (`AiError` from
  the ai client modules, `PlatformError` from `http.platform` and
  `persistence.user_directories`), and `EventLogRemote.when_authenticated` and
  `Flusher.register` reject a non-effect argument with a `TypeError`.
- `tests/test_service_docs.py` now also fails for any public service that holds an operation
  in a field.
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
  `Exclude` at each call), so `to_asgi` refuses its result: name the services in the helper's
  parameter (`services: Layer[Users | Db, E]`), or apply `provide_request` outside the helper.
- Attributes Effect has `readonly` are read-only, so assigning one is a pyright error: an
  atom's `read` and a writable atom's `write` (`Final`), `router.Middleware.layer`,
  `SqlRequest.payload`, and the fields of `workflow.Activity`, `Workflow`, `DurableDeferred`
  and `DurableQueue` (properties). Make a new value instead of assigning one (`make`,
  `annotate`). The classes now take Effect's
  variance (see Added). `tests/test_variance.py` no longer lets a writable attribute pass
  as read-only, and fails on a `Final` slot of a class whose variance pyright infers, which
  pyright still reads as writable.
- `rpc.make("Tag", ...)` types the RPC with its tag as a `Literal`, a new last type parameter
  of `Rpc` / `StreamRpc` (`Rpc[P, S, E, M, MT, Tag]`, `str` by default), and `prefix` makes it
  `str`. An `assert_type` of a made RPC now spells the tag
  (`rpc.Rpc[str, User, NotFound, Never, Never, Literal["GetUser"]]`); annotations without it
  still accept the RPC. `Handlers` / `EntityHandlers` gain a third, invariant parameter, the
  tags still without a handler (`Never` for a group that does not list its tags), and
  `Bound` / `StreamBound` two more (the RPC's tag and that list): code naming these types
  adds `Never`, or uses the type `handlers()` returns.

### Removed

- `cause.merge`, deprecated since 0.5.3: combine causes with `a + b` (Effect's
  `Cause.combine`, which never elects defects). Where the old electing result is wanted, write
  `(a + b).elect_defects()`.

### Added

- An RPC group or cluster entity can list its RPC tags,
  `class Counter(Entity[Literal["Increment", "Get"]])` or
  `class Users(RpcGroup[Literal["GetUser"]])` (`RpcGroupWith[Auth, Literal[...]]` with group
  middleware), and pyright then checks its handlers as TypeScript checks Effect's `toLayer`:
  `to_layer` / `to_layer_effect` reject them while an RPC has none, and a second handler for
  an RPC is an error. Python can't gather a class's attributes into a type, so the list
  repeats the tags; the class is checked against it when it is defined (a `TypeError` names
  each tag missing on either side). Groups that list nothing are unchanged: `to_layer` raises
  `ValueError` for a missing handler. Pyright tracks RPCs by tag, so a second handler given
  after all have one is not caught, and an RPC needs a literal tag at `rpc.make`.
- `workflow.Activity`, `DurableDeferred` and `router.Middleware` are covariant, `Workflow`
  and `DurableQueue` in their success and error, and `SqlRequest` in its payload, as in
  Effect: an `Activity[int, ...]` is accepted where an `Activity[object, ...]` is expected.
  `DurableDeferred.succeed` / `fail` / `done` / `into`, `DurableQueue.worker` and
  `Workflow.to_layer` bind their value types through `self`, so a wrongly typed value or
  handler is still an error.
- `help()` on a layer constant shows the constant's own docstring (the one below its
  assignment, which IDEs show on hover and the API reference reads) instead of the `Layer`
  class's: `help(otel.tracer.layer)` now says to provide an `OtelTracerProvider`. Every public
  layer constant has one, and a test keeps it that way.
- `JsonWebKey` is importable from `pyfect.crypto.key_format`, next to the `jwk` format that
  reads it.
- Docstrings for `Queue.unbounded`, `bounded`, `dropping` and `sliding` (including that
  `sliding(0)` accepts offers but wakes no waiting taker, as in Effect) and for
  `PubSub.unbounded`. A test requires a docstring on every public function and constructor of
  the stream, channel, sink, pull, queue and pubsub modules.

### Fixed

- A `Pool.make_with_ttl` made inside `acquire_release`'s acquire closes with its scope again;
  closing it used to wait forever once the pool's TTL strategy fiber had started. The cause was
  `uninterruptible_mask`: an uninterruptible caller got a `restore` that made the effect
  uninterruptible, where Effect's is the identity, so a fiber forked with `restore(...)` (the
  pool's strategy and first resize) could not be interrupted. `restore` is now the identity
  there, as in Effect. A new test builds every resource that forks a background fiber (pools,
  `RcRef`, `RcMap`, `ScopedCache`, `LayerMap`, fiber sets, maps and handles, shared and
  broadcast streams, `fork_scoped`) inside an acquire and checks its scope closes.
- An idle keep-alive connection no longer holds a TLS server's shutdown. asyncio kept a closed
  TLS connection open until the client sent its `close_notify`, up to 30 seconds, so
  `hypercorn_server` took 30 seconds to stop (HTTP/1.1 and HTTP/2) whatever
  `graceful_shutdown_timeout` said, and `uvicorn_server` waited out the whole timeout. Their TLS
  connections now close once their own `close_notify` is sent, as Node's and `live_server`'s
  do, so idle connections close at once, as Effect's `NodeHttpServer` closes them. A test
  times each adapter's shutdown, cleartext and TLS, HTTP/1.1 and HTTP/2, and fails when a new
  server module is left out of it.
- `live_server` counts a connection as idle once its request is read and its response
  finished, as Node's `closeIdleConnections` does, instead of once the serving fiber came back
  round for the next request. A shutdown starting just after a client got its response no
  longer waits out `graceful_shutdown_timeout` for that connection.
- `help()` and `inspect.signature` show typed signatures instead of `Any` for
  `Stream.transduce`, `aggregate`, `aggregate_within`, `channel.from_transform`,
  `from_transform_bracket`, `stream.transform_pull`, `transform_pull_bracket` and `sink.make`.
  A test keeps the remaining `Any` signatures in those modules from growing.
- `share(idle_time_to_live=...)`'s docstring said a later reader continues where it left off:
  what the upstream publishes while no reader is subscribed is lost, except the last `replay`
  chunks, as in Effect.
- A pin in the type checks keeps `JoseError.reason` the union of reasons, with no `Unknown`.

### Docs

- On a wide screen the page no longer jumps sideways while it loads. The browser draws these
  long pages before it has read all of them, and until it reached the table of contents on the
  right, the article was centred as if the table of contents took no space.
- asyncio-apps.mdx said uvicorn's TLS was the same as hypercorn's `certfile` and `keyfile`,
  which made uvicorn raise a `TypeError`. A new "Serving over TLS" section serves the same app
  over TLS on both, with hypercorn's `certfile`/`keyfile` and uvicorn's
  `ssl_certfile`/`ssl_keyfile`, in a tested snippet. A test requires every TLS setting a guide
  names to be a real setting of one of the servers and to be passed by a snippet of that guide.
- Mounting an ASGI app under a path takes `router.prefix_route(...)`, which gives the app the
  prefix as its `root_path`; `asgi.from_asgi` passes on HTTP requests only (as Effect's
  `fromWebHandler`), while `router.to_asgi` does bridge WebSockets. Both in the guides and
  in `help(asgi.from_asgi)`.
- `router.schema_json`'s schema is a struct of `body`, `method`, `url`, `headers`, `cookies`,
  `pathParams` and `searchParams` (camelCase, as in Effect), in http-server.mdx, its snippet
  and the docstrings.
- crypto.mdx has an "Encrypted tokens" section (`jwt.encrypt`/`decrypt` and `jwe`, with the one
  supported pair `dir` + `A256GCM`, as in Effect, and what is refused) and a "Wrapping to a
  public key" section (`key_wrap.rsa_oaep_sha256` and `rsa_oaep_sha1`, which hash each uses,
  and importing an RSA public JWK), each with a tested snippet.
- streams.mdx has a "Rollups" section (`transduce`, `aggregate`, `aggregate_within`, how
  `fixed` and `spaced` count time, and what an upstream failure does to the open run) and a
  "Custom operators" section on writing a `Channel` with `channel.from_transform`. It shows how
  to count a sliding `Queue`'s drops by numbering offers, and concurrency.mdx has a Queues
  section.

## 0.5.7 (2026-11-11)

### Added

- `S.new(A, **options)` is a schema class's constructor with parse options, Effect's
  `new A(props, options)`: `S.new(A, disable_checks=True)(x=1)` builds the instance without
  running its fields' or its `@S.class_check` checks, still checking the fields' types and
  applying their defaults. It is typed with `A`'s own keyword signature.

### Performance

- The event log and cluster constructors that Effect builds with `disableChecks` skip their
  checks too (`compact_backlog`, journal and SQL storage rows, `runner.make`,
  `runner_address.make`, `entity_address.make`). A construction with `disable_checks` that
  succeeds parses each field once instead of through the whole struct: building 150 thousand
  entries takes about half as long.

### Fixed

- Ported event log tests build entries with `S.new(Entry, disable_checks=True)` wherever Effect's
  tests pass `{ disableChecks: true }`, so the large-group `compact_backlog` tests no longer
  time out on slower CI runners. A new test fails when a port drops the option again.

## 0.5.6 (2026-11-11)

### Fixed

- ISO strings for years before 1000 have four digits, as JavaScript's `toISOString`
  (`0999-12-31T23:59:59.999Z`). On Linux with Python 3.13 they came from glibc's
  `strftime("%Y")`, which wrote `999-12-31T...`: `date_time.format_iso`, the `DateTimeUtc`
  schemas' encodings (which then did not decode), log timestamps, date bound annotations and
  the CLI wizard's dates.
- A recursive `FileSystem.watch` on Linux reports a file made in a new directory with
  `Create`. When inotify began watching the directory between the file's creation and its
  first write, the first event for the file was an `Update`.
- An offer to a full `Queue` that found room while it parked could report an interrupt with
  its item already queued: a callback resumed while it registered handed its result to the
  next step, where a step-budget pause let an interrupt drop it. Any `fx.callback` whose
  `register` resumes at once now hands its result straight to its continuation.
- `TestClock.adjust` no longer gives up with a spurious `BusyFiberWarning` (stalling for
  `warning_delay`) when the fiber it woke finished while `adjust` paused for its step budget.
- Found by a new deterministic interleaving harness for the fiber runtime (`tests/interleave`),
  which explores the order of scheduled tasks, timers and simulated threads systematically and
  replays any failure from its schedule.

### Added

- 68 generic classes that were invariant only because of how they were declared now have
  Effect's variance, so a narrower one is accepted where a wider one is expected
  (`FiberSet[int, E]` as a `FiberSet[object, E]`, a list mixing two RPCs). Pyright made
  every frozen dataclass and `NamedTuple` with PEP 695 parameters invariant; these classes
  now declare their variance:
  - covariant: `HashMap`, `HashSet`, `HashMapSchema`, `HashSetSchema`, `FiberHandle`,
    `FiberSet`, `FiberMap` (value and error; keys stay invariant), `Cache` / `ScopedCache`
    (requirements), `rpc.Rpc` / `StreamRpc` (success and error),
    `workflow_proxy.WorkflowRpcs`, `effectable.Class`, `cluster` replies and
    `EntityResource`, the `cli.param` classes, `cli.prompt.Choice`, `cli.Nested`, `jose.jwt`
    results, `json_schema` documents, `http_api.schema` wrappers, `ai.decision.Level` /
    `Rate`, `ai.mcp_schema` classes, `persistence.redis.Script` and
    `graphql.client.NodesConnection`;
  - contravariant: `cli.Command`'s input (Effect's `in Input`), `sql.model.Repository` /
    `Resolvers` inputs, `sql.stream.Emit`, `ai.tool.HandlerContext`.

  Methods that take a value (`HashMap.set`, `HashSet.add`, `FiberSet.add`,
  `Command.with_handler`, ...) bind it through `self`, so `HashMap[str, int].set("b", "x")`
  is still an error. `FiberHandle` / `FiberMap` / `FiberSet` `.deferred` is typed
  `Deferred[None, Any]`, as Effect's `Deferred<void, unknown>`. `tests/test_variance.py`
  pins every public generic class's variance; a change that makes one stricter fails the
  pyright run.
- Docstrings for every method and property of the public services that already had them as
  methods, so `help()` and the API reference describe them: `HttpClient`, `FileSystem`, `Path`,
  `Clock.sleep`, `Sharding`, `Runners`, `MessageStorage`, `AtomRegistry`, `LayerMap`,
  `LayerRef`, the SQL clients (`dialect`, `join`, `load_extension`) and `PgPool`, the eventlog
  storages, encryption and server services, `McpServer`, `McpClient`, `EmbeddingModel`,
  `Tokenizer` and more, each checked against Effect 4.1.2. `tests/test_service_docs.py` (which
  replaces the crypto-only check) fails for any public service method or property without one.

### Docs

- A "Threads and throughput" guide, linked from the streams and asyncio guides: all of a run's
  fibers share one thread, free-threaded 3.14t speeds up only work on other threads
  (`fx.blocking`, sockets, workers), CPU-heavy work belongs in `fx.blocking` or other
  processes, the throughput `benchmarks/streams.py` measures, rechunking items that arrive one
  at a time before `group_by`, and how to spot a saturated run.

## 0.5.5 (2026-11-10)

### Changed

- `config.duration(...)` returns a `config.DurationConfig`, a `Config[Duration]` whose
  `with_default` also takes a duration input: `with_default("1 second")` is a
  `Config[Duration]` (it was `Config[Duration | str]` and gave the string), and an invalid one
  raises when it is given. `nested` keeps it a `DurationConfig`.
- `clock.current_time_millis()` is a `float` on the live clock too (whole milliseconds, as
  `Date.now()`); it was an `int` there and a `float` under the `TestClock`.
- `fx.blocking` / `fx.try_blocking` run on daemon threads that exit after 10 seconds idle,
  where a `ThreadPoolExecutor` kept every thread for the process's life and joined them at
  exit. Effect has no thread pool (Node runs such work on libuv's), so this follows Python's
  norm for work a program may abandon: a process whose blocking work was interrupted, and is
  still running, now exits at once instead of waiting for it.
- Faster streams and fibers, with the same results. `group_by_key` serves each key of a chunk
  whose group is open and has room in one step (Effect's `RcMap.touch` and `Queue.offerAll`,
  without their effects), `forever` is one loop frame (Effect's `whileLoop`), `on_exit` (and
  `ensuring`, `on_error` and every channel's per-pull error handler) is one primitive (Effect's
  `OnExit`), `Queue.offer` adds an item that fits in its own step as Effect's `offer` does, and
  `isinstance` checks take tuples (`A | B` built a union on every call, once per fiber step).
  On CPython 3.14, `group_by_key` + `flat_map` runs about 3.7M items/s in chunks of 256 (was
  520k) and 285k/s in chunks of one (was 84k); with a `grouped_within` per group, 2.0M (was
  350k) and 195k/s (was 69k). `benchmarks/streams.py` measures these.
- A fiber pauses for its step budget where Effect does: before the step that reaches
  `MaxOpsBeforeYield`, the resumed run counting the pause's continuation. A producer that never
  waits now offers 1023 items between a waiting consumer's turns, as in Effect (it was 683),
  and a full bounded queue of 1024 no longer hands over one item per fiber switch.

### Added

- HTTP server guide: serving WebSockets with `request.upgrade`, and Effect's rules for them: the
  socket opens only when its reader is taken (a handler that only writes hangs), a write after
  the reader's scope closes waits forever, and a normal close fails `reader.pull` and
  `to_stream` with code 1000.
- Streams guide: `throttle` (the bucket starts at `units`; `"enforce"` keeps or drops whole
  chunks), `group_by` / `group_by_key` (one slow group stalls every key), `broadcast`,
  `broadcast_n` and `share` (capacity counts chunks), with checked examples; no operator
  reports its drops, as in Effect; `ndjson.decode` fails the whole stream at a bad line.
- Docs: two multi-tenant warnings, both matching Effect. A SQL resolver shared by tenants
  batches their requests onto the first request's client (make one per tenant: SQL guide), and
  a `LayerMapService` lookup that reuses a module-level layer constant gives every key built
  while it is held the first key's build (make per-key layers in the lookup: Resources guide).
  Also: a `THROW` under `XACT_ABORT ON` inside `with_transaction` dies with error 3903 beside
  it, and `mssql.error.error_number` reads a custom error's number (SQL Server guide);
  branded values with `S.refine` and `S.from_brand` (Schema guide); calling `make_resolvers`'
  resolvers (Models guide); `LayerMapService[K, I, E]`'s lookup error parameter; a middleware's
  several errors as a tuple, since an `S.Union` is one schema answering with the union's status
  (500 unless annotated), as in Effect (HttpApi guide, pinned by
  `tests/test_http_api_union_errors.py`).
- Guide: [Adopting in an asyncio app](/docs/asyncio-apps): a `ManagedRuntime` in the app's
  lifespan, mapping typed errors at the seam (`run_async` takes only `Never` errors), sharing
  layers between runtimes with `memo_map`, which `contextvars` cross `run_async`, `from_async`
  and a fork, `router.provide_request`, routes mounted with `to_asgi`, and `hypercorn_server`
  with the legacy app mounted through `from_asgi`. HTTP server links to it.

### Fixed

- The `TestClock`'s warnings reach a `warnings.catch_warnings()` or `pytest.warns` around the
  code that caused them again on free-threaded Python, where warning filters are per context
  (a 0.5.4 regression): `adjust`'s `BusyFiberWarning` is raised by the adjusting fiber, and
  the not-advancing warning in the context of the sleep that armed it, as Effect's warning
  fiber inherits it. A timer callback that warns in its own context is a test failure
  (`tests/test_timer_warnings.py`).
- `sql.model.make_repository(...).insert` works on SQL Server: the insert asks the statement
  compiler for its row (`sql.insert(row).returning("*")`, as Effect's `SqlModel` does), which
  SQL Server writes as `OUTPUT INSERTED.*`, where the model sent its own `returning *`.
  `update` still appends `returning *`, as Effect's does, so on SQL Server and ClickHouse
  only `update_void` works (in Effect too). On MySQL an update's follow-up `SELECT` no longer
  repeats the soft-delete filter. Every statement the repositories and resolvers send is
  pinned against Effect's on each dialect's compiler.
- `hypercorn_server` no longer prints hypercorn's own "Running on" line: the listen log is
  `serve`'s alone, so `disable_listen_log=True` leaves out every startup line, as with Effect's
  `NodeHttpServer`, which logs nothing itself.
- `router.add_all([...])` takes a list mixing routes of different error or requirement types:
  `Route` is now covariant (pyright inferred a frozen dataclass's parameters as invariant), so
  such a list matched no overload.

## 0.5.4 (2026-11-10)

### Fixed

- Concurrent runs no longer see each other's `contextvars`. A fiber whose first run was
  scheduled ran in the context of whatever drained the scheduler: concurrent
  `ManagedRuntime.run_async` calls on one loop all read the first caller's request id, a
  `ManagedRuntime.run_blocking` / `run_sync` / `run_fork` from one thread could run in the context
  of another thread driving the runtime, and so could `fx.run_fork(eff, scheduler=...)`, a
  `FiberSet` runner and a forked child that is not started immediately (in an ASGI app too). A
  scheduled first run now takes a copy of its starter's context, as Effect's runs follow Node's
  `AsyncLocalStorage`. `fx.run_sync` and `fx.run_blocking` still run in the caller's own context;
  `ManagedRuntime.run_sync` / `run_blocking` run in a copy, so a `ContextVar` the effect sets
  is not the caller's afterwards (Effect's `runSync` shows it; matching it would deadlock runs
  that wait on each other across threads).
- `ManagedRuntime.run_async` / `run_async_exit` after `dispose` die with
  `RuntimeError("ManagedRuntime disposed")`, as every other entry point and Effect's
  `runPromise` do, instead of failing with an interruption. The effect starts at once, up to its
  first wait, as Effect's `runPromise` evaluates it.

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
