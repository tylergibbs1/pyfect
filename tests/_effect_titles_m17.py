# ruff: noqa: E501 (Effect test titles, kept whole so they match)
"""Effect 4.1.2 test titles not ported yet (milestone M17, the move from Effect 4.0.6).

Each M17 agent ports the titles of its area and deletes them here; an empty file closes the
milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M17_REASON = "NOT_PORTED new in Effect 4.1.2 (milestone M17), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {
    "effect/test/Migrator.test.ts": ("fromRecord loads migrations without filesystem services",),
    "effect/test/graphql/GraphQLProtocol.test.ts": (
        "a 500 with data and errors is a ResponseError even with partial: true",
        "a 503 with data: null and no errors is a TransportError carrying its Retry-After",
        "a \x00 503 with data and no errors is a TransportError, not a result",
    ),
    "effect/test/http/Cookies.test.ts": (
        "isolates host-only cookies without overwriting another host's session",
        "uses the response's default path and matches explicit paths on segment boundaries",
        "accepts matching Domain cookies but rejects foreign, single-label and IP domains",
        "deletes cookies with Max-Age=0 and does not send expired cookies",
        "ignores invalid Max-Age attributes",
        "normalizes leading dots and case in seeded cookie domains",
        "replaces a Domain cookie with a host-only cookie of the same name and path",
        "sends Secure cookies only over HTTPS",
        "serializes same-name cookies longest path first",
        "trims cookie pairs and ignores invalid cookie names",
        "unquotes values surrounded by whitespace",
    ),
    "effect/test/http/FetchHttpClient.test.ts": (
        "buffers unsupported streaming only when explicitly opted in",
        "keeps supported request bodies streaming with duplex half",
        "rejects unsupported streaming without sending the request",
    ),
    "effect/test/http/FindMyWay/params-collisions.test.ts": (
        "node with longer static suffix should have higher priority when registered first",
    ),
    "effect/test/http/HttpClient.test.ts": (
        "bounds the whole retry loop when applied after retryTransient",
        "classifies transient responses and errors",
        "fails with a TransportError and aborts the request",
        "gives each retryTransient attempt a fresh budget",
        "keeps withScope aborting a request that withCookiesRef adds cookies to",
        "selects stored cookies for each redirect hop",
        "sends stored cookies when the URL is prepended after withCookiesRef",
        "sends stored response cookies only to the matching host",
        "stores cookies using the final response host and default path",
    ),
    "effect/test/http/HttpClientRequest.test.ts": (
        "does not add a Content-Type when compressing a request without one",
        "preserves an explicit Content-Type when compressing $name",
        "preserves an extension method from a web request without claiming it is a known method",
    ),
    "effect/test/http/HttpCompression.test.ts": ("ignores empty Accept-Encoding members",),
    "effect/test/http/HttpMiddleware.test.ts": (
        "keeps a synthesized 5xx span failure redacted after the request completes",
    ),
    "effect/test/http/HttpServerError.test.ts": (
        "formats an absolute request URL as its path",
        "omits the query string",
    ),
    "effect/test/http/HttpServerRequest.body.test.ts": (
        "fromClientRequest fails buffered reads over MaxBodySize",
    ),
    "effect/test/http/HttpServerRequest.test.ts": (
        "preserves an extension method through web-server-client conversion",
        "urlParamsBody preserves a leading BOM",
        "urlParamsBody preserves leading question marks",
    ),
    "effect/test/http/HttpStaticServer.test.ts": (
        "evaluates preconditions before cache validators and ranges",
    ),
    "effect/test/http/HttpTraceContext.test.ts": (
        "reads the sampled bit from W3C trace flags",
        "rejects malformed W3C trace flags: %j",
        "rejects uppercase W3C identifiers: %s",
    ),
    "effect/test/http/Mime.test.ts": ("looks up script source types",),
    "effect/test/http/ProblemDetails.test.ts": (
        "decode drops wrong-typed members, defaults type and keeps extensions",
        "encode always emits type",
    ),
    "effect/test/httpapi/HttpApiBuilder.test.ts": (
        "accepts each listed content type for byte and NDJSON stream payloads",
        "rejects endpoints that share a method and path",
        "sends the first listed stream content type unless a declared header selects another",
    ),
    "effect/test/httpapi/HttpApiClient.test.ts": (
        "decodes a response-only body that arrives after the head",
        "decodes a stream with listed content types regardless of the received content type",
        "fails with declared errors like decoded-only",
    ),
    "effect/test/httpapi/HttpApiEndpoint.test.ts": (
        "accepts an upgrade with $name",
        "rejects buffered payloads and successes on any listed stream content type",
    ),
    "effect/test/httpapi/HttpApiProblemDetails.test.ts": (
        "adds a problem+json 400 to the OpenAPI spec",
        "adds a problem+json 500 to the OpenAPI spec",
        "adds errors prefixed with the slot name when includeDetails is enabled",
        "decodes the 500 into InternalServerErrorProblem",
        "decodes the response into the class instance",
        "discriminates decoding by type and keeps the declared status",
        "encodes a built-in error as a problem",
        "keeps the empty 400 without the middleware",
        "lists application/problem+json under the status in the OpenAPI spec",
        "rejects a body with a different type",
        "renders a generic problem+json 400 without details",
        "renders a generic problem+json 500 and reports the schema error once",
        "responds with the declared status and a problem+json body",
    ),
    "effect/test/httpapi/HttpApiSchema.test.ts": (
        "encodes data with its JSON codec",
        "rejects empty and duplicate content type lists",
        "stores a list of content types with the first as the default",
    ),
    "effect/test/httpapi/OpenApi.test.ts": (
        "emits each listed stream content type in declared order",
        "requires every stacked security middleware",
    ),
    "effect/test/persistence/KeyValueStore.test.ts": (
        "derives clearPrefix from keys",
        "keys",
        "scopes keys, size, isEmpty and clear to the prefix",
    ),
    "effect/test/persistence/KeyValueStoreTest.ts": (
        "clearing a prefixed view preserves keys outside its namespace",
        "clears keys beyond a prefix followed by U+FFFF",
        "keys",
        "matches prefixes case-sensitively",
        "treats SQL wildcard and escape characters literally",
    ),
    "effect/test/process/ChildProcess.test.ts": (
        "template form groups quoted words and keeps values literal",
        "template form throws for shell syntax",
        "template form with the shell option keeps the script as written",
    ),
    "effect/test/process/ChildProcessSpawnerTest.ts": (
        "should group quoted words",
        "should not expose Redacted values in errors",
        "should pass Redacted arguments and environment values",
        "should read a reply on the same fd after pipeTo ends its input",
        "should reject arguments together with shell",
        "should remove variables set to undefined",
        "should report a write failure to a later reader without an uncaught error",
        "should run the command as a shell script",
        "should use only env by default",
    ),
    "effect/test/process/CommandLine.test.ts": (
        "adds one argument per array element",
        "joins a program and its arguments",
        "joins values with the surrounding argument",
        "makes arguments with Redacted values Redacted",
        "masks Redacted words, escapes control characters and accepts any input",
        "quotes Windows arguments",
        "quotes Windows program names without backslash escapes",
        "quotes for POSIX shells",
        "quotes for PowerShell",
        "rejects an unclosed quote around a value and invalid escapes",
        "rejects syntax that needs a shell",
        "rejects the argument --% for PowerShell",
        "removes POSIX quotes and escapes",
        "splits the text and keeps values literal",
    ),
    "effect/test/rpc/RpcClient.test.ts": (
        "completes a discarded call on its acknowledgement, not on the write",
        "does not acknowledge a chunk dropped when its stream consumer is interrupted",
        "fails a discarded call on a transport error and interrupts its pending send",
        "fails only the calls on a crashed pooled worker",
        "sends a discarded call to a worker as a request and waits for its Exit",
        "stops the server stream promptly when an acknowledged stream consumer is interrupted",
    ),
    "effect/test/rpc/RpcServer.test.ts": (
        "fails a discarded call with its own Exit, not a Defect, when it fails before its acknowledgement",
        "fails requests with malformed headers, whether the payload decodes synchronously or not",
        "keeps interrupting disconnected clients while an onDisconnect callback is pending",
        "runs overlapping JSON-RPC notifications and drops invalid ones, without replying to any",
        "sends nothing for a running \x00, but reports its failure",
    ),
    "effect/test/sql/SqlClient.test.ts": (
        "acquires under the transaction span and records the wait for the connection, not BEGIN",
        "ends each control span with its own exit when the body or COMMIT fails",
        "replays the whole transaction when Effect.retry recovers a serialization failure at COMMIT",
        "traces controls without span propagation, but records no wait time or events, and none without tracing",
        "traces each transaction control as a client span of its transaction level",
    ),
    "effect/test/sql/Statement.test.ts": (
        "binds plain objects shaped like fragments or segments as parameters",
    ),
    "platform/node-shared/test/NodeChildProcessSpawner.test.ts": (
        "quote arguments and escape control characters",
    ),
    "platform/node/test/HttpApi.test.ts": (
        "closes an upgraded connection when interrupted as the upgrade is taken",
        "closes an upgraded connection whose headers fail to decode",
    ),
    "platform/node/test/KeyValueStore.test.ts": (
        "keys decodes file names",
        "remove succeeds for a missing key",
    ),
    "platform/node/test/NodeHttpClient.test.ts": (
        "followRedirects releases redirect response bodies with a single socket",
        "followRedirects releases scoped redirect response bodies with a single socket",
        "reads backpressured form data files on demand and releases them on interruption",
        "request and response urlParamsBody preserve a leading question mark",
        "returns TransportError when a form data file stream cannot be created",
    ),
    "platform/node/test/NodeHttpServer.test.ts": (
        "completes a $body response sent on $event after a disconnect",
        "redacts configured headers when inspecting requests",
    ),
    "platform/node/test/NodeMultipart.test.ts": (
        "fails with a typed parse error when the source terminates early",
        "leaves the source open on interruption and handles its later error",
        "removes its source listeners after parsing",
    ),
    "platform/node/test/NodeRedis.test.ts": (
        "bounds shutdown while a command is stalled",
        "interrupts a stalled \x00 handshake",
        "interrupts a stalled reserved connection",
        "interrupts a subscriber stalled on \x00",
    ),
    "platform/node/test/NodeSocket.test.ts": (
        "batches synchronous duplex drains and completes in order (\x00)",
    ),
    "platform/node/test/OpenApi.test.ts": ("Upgrade with an ordinary success",),
    "platform/node/test/fixtures/rpc-e2e.ts": (
        "completes a discarded call on its acknowledgement, and fails it when its middleware rejects it",
    ),
    "sql/clickhouse/test/Client.test.ts": (
        "binds plain objects shaped like ClickHouse params as String parameters",
        "writes the ledger with commands and runs migrations as queries",
    ),
    "sql/libsql/test/Client.integration.test.ts": (
        "overlaps remote statements with each other and open transactions",
        "serializes local statements behind open transactions",
    ),
    "sql/mssql/test/Cancellation.integration.test.ts": (
        "can query after interrupting a request in a single-connection pool",
    ),
    "sql/mssql/test/Client.integration.test.ts": (
        "runs the next statement on a connection whose running statement was interrupted",
    ),
    "sql/mssql/test/KeyValueStore.integration.test.ts": (
        "clearing a store preserves a differently cased store with a distinct entry key",
    ),
    "sql/mysql2/test/Cancellation.integration.test.ts": (
        "a stream consumer can run statements on the same connection once the streamed statement ends",
        "ending a stream early stops the statement",
        "ending a stream whose remaining rows are already buffered keeps the connection",
        "interrupting a pending reservation returns promptly and releases the late connection",
        "interrupting a running statement kills it",
        "interrupting a statement queued on a shared connection leaves the running one alone",
    ),
    "sql/mysql2/test/MysqlClient.integration.test.ts": (
        "kills a stream's statement when interrupted before the first row",
        "gives a shared connection back when the kill connection cannot be created",
        "keeps the connection when a cancelled stream settles before its kill is registered",
    ),
    "sql/pg/test/Client.integration.test.ts": (
        "ends transactions whose prepared statements went missing",
    ),
    "sql/pg/test/PgPool.in-process.test.ts": (
        "reports a cold transaction's connect and control statements under its transaction span",
        "PgClient.make reports the occupancy of its pool",
        "PgClient.makeClient reports its one session as permanently leased",
        "counts a multiplexed session once however many fibers share it",
        "does not reuse a session left in an aborted transaction",
    ),
    "sql/sqlite-node/test/Client.test.ts": (
        "releases the connection when a queued transaction is interrupted",
    ),
    "sql/sqlite-node/test/Resolver.test.ts": (
        "keeps requests in another client's transaction out of its batch",
        "keeps requests outside a transaction out of its batch",
        "keeps requests without the transaction service out of its batch",
    ),
}
