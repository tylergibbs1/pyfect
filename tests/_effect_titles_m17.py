# ruff: noqa: E501 (Effect test titles, kept whole so they match)
"""Effect 4.1.2 test titles not ported yet (milestone M17, the move from Effect 4.0.6).

Each M17 agent ports the titles of its area and deletes them here; an empty file closes the
milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M17_REASON = "NOT_PORTED new in Effect 4.1.2 (milestone M17), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {
    "effect/test/Migrator.test.ts": ("fromRecord loads migrations without filesystem services",),
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
    "effect/test/workflow/Workflow.test.ts": ("keep their SHA-256 derived values",),
    "effect/test/workflow/WorkflowEngine.test.ts": (
        "layerMemory \x00 an interrupted child without interrupting its sibling",
    ),
    "platform/node-shared/test/NodeChildProcessSpawner.test.ts": (
        "quote arguments and escape control characters",
    ),
    "platform/node/test/KeyValueStore.test.ts": (
        "keys decodes file names",
        "remove succeeds for a missing key",
    ),
    "platform/node/test/NodeRedis.integration.test.ts": (
        "renews an expired lease before recovery revokes ownership",
        "revoked ownership cannot settle recovered work before reacquisition",
        "same-store stale success preserves the replacement and its refresh registration",
        "stale interruption does not release a replacement or decrement its attempts",
        "success after lease expiry but before reset is not redelivered",
    ),
    "platform/node/test/NodeRedis.test.ts": (
        "bounds shutdown while a command is stalled",
        "interrupts a stalled \x00 handshake",
        "interrupts a stalled reserved connection",
        "interrupts a subscriber stalled on \x00",
    ),
    "platform/node/test/cluster/ShardFence.integration.test.ts": (
        "a runner that lost its advisory lock cannot store a reply",
        "a runner that lost its lease cannot store a reply",
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
    "sql/sqlite-node/test/SqlEventJournal.test.ts": (
        "writeFromRemote reports each conflict once for a batch over the statement parameter limit",
        "writeMany commits a batch over the statement parameter limit",
    ),
}
