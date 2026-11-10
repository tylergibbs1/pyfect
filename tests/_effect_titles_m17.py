# ruff: noqa: E501 (Effect test titles, kept whole so they match)
"""Effect 4.1.2 test titles not ported yet (milestone M17, the move from Effect 4.0.6).

Each M17 agent ports the titles of its area and deletes them here; an empty file closes the
milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M17_REASON = "NOT_PORTED new in Effect 4.1.2 (milestone M17), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {
    "effect/test/cluster/ClusterWorkflowEngine.test.ts": (
        "DurableDeferred.raceAll replays a persisted result its owner has not processed yet",
        "applies a persisted interrupt when a fresh owner replays a failure-suspended workflow after a transient \x00 lookup failure",
        "completes \x00 after a transient failure \x00 it",
        "keeps a newer activity reply when a stale Suspended reply resets the attempt",
        "reacquires shards after a forced release interrupts a parent resume waiting on its active run",
        "replays a raced activity that starts during shutdown on the next owner",
        "runs an activity once after a transient failure \x00 its request",
        "wakes the parent when a suspended child is interrupted",
    ),
    "effect/test/cluster/Runners.test.ts": (
        "a custom runner's failed send notification fails the caller only outside a transaction",
        "notifies a discarded persisted send only after its transaction commits",
    ),
    "effect/test/cluster/Sharding.test.ts": (
        "hands each shard off once when a joining runner's membership refresh stalls",
        "runs each singleton on one new runner when a joining runner's acquisition is slow",
        "WithTransaction replays the request when saving the reply aborts the transaction",
        "abandons a fenced transactional reply without restarting the entity",
        "abandons a reply once lock storage no longer attributes the shard to this runner",
        "answers a remembered interrupt once when its queued request is dispatched",
        "backs off defect restarts per entity and resets after recovery",
        "finishes a persisted reply that completes while shutdown starts",
        "hands each shard off once across a staggered cluster startup",
        "hands each shard off once for a bounded burst of staggered joins",
        "hands each shard off once when membership refresh fails during pending joins",
        "hands each shard off once when runners poll membership out of phase",
        "interrupting a request that keeps defecting does not stall other entities",
        "interrupts a replayed request whose interrupt arrives before the rebuild publishes",
        "keeps a queued request cancelled when its interrupted reply fails",
        "publishes continuous joins within four settle windows",
        "publishes unhealthy runners immediately while joins are settling",
    ),
    "effect/test/cluster/Snowflake.test.ts": (
        "makeGenerator keeps ids unique after repeated sequence overflow",
    ),
    "effect/test/eventlog/EventJournal.test.ts": (
        "makeEntryIdUnsafe increases strictly, and encodes an explicit msecs exactly",
    ),
    "effect/test/eventlog/EventLog.test.ts": (
        "bootstraps a new device from the snapshot a background run commits, ending with the state of a full replay",
        "serves a device whose cursor is inside one snapshot everything kept by the next",
    ),
    "effect/test/eventlog/EventLogEncryption.test.ts": (
        "decrypts batches written before the crypto module migration",
        "dies when a recorded batch is replayed for another store",
        "encrypts in the recorded format on the crypto services in context",
    ),
    "effect/test/eventlog/EventLogRemote.test.ts": (
        "is absent when the server does not advertise compaction",
        "makeEncrypted authenticates an existing identity with its bound signing key",
        "resends a whole segment after a dropped connection",
        "uploads kept entries in segments of about 512 KB, splitting an oversized one, with their original bytes",
    ),
    "effect/test/eventlog/EventLogRemoteCompaction.test.ts": (
        "fails the run when a compactor dies",
        "fails the run when the kept set does not survive another pass",
        "folds chunks that grow with the kept set into the entries kept so far",
        "keeps entries holding values the schema cannot read",
        "keeps entries with fields the schema does not know, even when the compactor drops them",
        "keeps the whole input of a call that outputs a new entry and carries on",
    ),
    "effect/test/eventlog/EventLogServerEncrypted.test.ts": (
        "fails Input with NotFound once the stage's pin was pruned",
        "accepts kept ids matched to a later occurrence of a repeated input id",
        "answers Begin with NotWanted below the threshold and logs no-ops while backing off multiplicatively",
        "isolates pending segment pieces and aborts by store on the same connection",
        "keeps activation off live changes and omits acks for re-uploads at or below the base",
        "logs snapshot commit counts and the committed and rollback activation ids",
        "loses the compare-and-swap after a rollback and frees busy on abort",
        "memory storage fails to start unless grace is longer than the lag and the stage TTL",
        "places every snapshot entry at or after its input sequence and at or below the base, without overlap",
        "rejects a commit whose kept ids are not a non-empty, in-order subsequence of the pinned input",
    ),
    "effect/test/eventlog/EventLogServerEncryptedCompactionTest.ts": (
        "fails an Input or Fetch read again after its stage's pin was pruned",
        "re-appends the withdrawn snapshot's input on rollback, so its readers end with every entry",
        "slides a stage's claim on each Part and rejects a stale Part after a steal",
        "acknowledges a retried segment without staging it twice",
        "fails changes when the active snapshot has no rows",
        "fails reads of an expired stage before the sweep closes it",
        "prunes the superseded originals after grace and then refuses to roll back to them",
        "releases the claim on abort and no-op, and clears the no-op state on commit",
        "reports as the lag head the last sequence of each storage hour once it ended a lag ago",
        "rolls back to the originals within grace, and the sweep leaves them",
        "serves the snapshot at or below the base and the originals above it",
    ),
    "effect/test/eventlog/EventLogServerUnencrypted.test.ts": (
        "Authenticate rejects a validly signed key that differs from the identity's binding",
        "Hello measures a challenge's time to live from after it was generated",
        "Authenticate accepts the challenge from an earlier overlapping Hello",
        "Authenticate does not bind a signing key whose signature fails verification",
        "Authenticate passes the presented signing key to identity authorization",
        "Authenticate rejects a challenge issued to a disconnected client",
        "Authenticate rejects a challenge older than its time to live",
    ),
    "effect/test/eventlog/EventLogSessionAuth.test.ts": (
        "fails with CryptoUnavailable when the WebCrypto object has no subtle",
    ),
    "effect/test/eventlog/EventRow.test.ts": (
        "compaction composes, including with older entries",
        "compaction is independent of input order",
    ),
    "effect/test/eventlog/SqlEventLogServerEncryptedStorageTest.ts": (
        "allocates sequences after an old instance's writes during a rolling deploy",
        "finishes the prune of a sweeper that died in the middle of it",
        "keeps sequences increasing after every original is pruned",
        "publishes nothing from a rollback whose outer transaction aborts",
        "publishes nothing from a write whose outer transaction aborts",
        "re-appends the withdrawn input in order at the head, before later writes",
        "resumes a partially pruned snapshot after its sweeper dies without deleting originals",
        "seeds a store written before the upgrade once when two instances open it together",
    ),
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
    "effect/test/persistence/BackingPersistenceTest.ts": (
        "clear only removes entries from the cleared store",
        "distinct store and key pairs do not alias",
    ),
    "effect/test/persistence/CircuitBreaker.test.ts": (
        "receives the admission's probe flag, so an outcome ignored when closed can reopen a probe",
        "allow: a rejection alongside an admit defect still dies without running the call",
    ),
    "effect/test/persistence/CircuitBreakerTest.ts": (
        "onRejection allow runs a refused call unrecorded, while an admitted call records and can take the probe",
    ),
    "effect/test/persistence/PersistedQueueTest.ts": (
        "settling a custom id does not release the same id in another queue",
    ),
    "effect/test/persistence/RateLimiter.test.ts": (
        "keeps state until it expires, then reclaims it while idle",
        "rejects positive token requests with a zero limit",
        "starts an expired token bucket fresh before the next sweep",
    ),
    "effect/test/persistence/RateLimiterTest.ts": (
        "a key ending in :adaptive does not share another key's adaptive state",
        "a key ending in :refill does not refill another key's token bucket",
        "store caps a zero limit and leaves an undefined limit uncapped",
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
    "effect/test/workflow/Workflow.test.ts": ("keep their SHA-256 derived values",),
    "effect/test/workflow/WorkflowEngine.test.ts": (
        "layerMemory \x00 an interrupted child without interrupting its sibling",
    ),
    "platform/node/test/HttpApi.test.ts": (
        "closes an upgraded connection when interrupted as the upgrade is taken",
        "closes an upgraded connection whose headers fail to decode",
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
    "platform/node/test/NodeRedis.integration.test.ts": (
        "renews an expired lease before recovery revokes ownership",
        "revoked ownership cannot settle recovered work before reacquisition",
        "same-store stale success preserves the replacement and its refresh registration",
        "stale interruption does not release a replacement or decrement its attempts",
        "success after lease expiry but before reset is not redelivered",
    ),
    "platform/node/test/NodeSocket.test.ts": (
        "batches synchronous duplex drains and completes in order (\x00)",
    ),
    "platform/node/test/OpenApi.test.ts": ("Upgrade with an ordinary success",),
    "platform/node/test/cluster/ShardFence.integration.test.ts": (
        "a runner that lost its advisory lock cannot store a reply",
        "a runner that lost its lease cannot store a reply",
    ),
    "platform/node/test/fixtures/rpc-e2e.ts": (
        "completes a discarded call on its acknowledgement, and fails it when its middleware rejects it",
    ),
    "sql/sqlite-node/test/SqlEventJournal.test.ts": (
        "writeFromRemote reports each conflict once for a batch over the statement parameter limit",
        "writeMany commits a batch over the statement parameter limit",
    ),
}
