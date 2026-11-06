const R = "/Users/tylergibbs/pyfect-ref/effect/packages/effect/src/"
const SchemaBinary = await import(R + "encoding/SchemaBinary.ts")
const { Schema } = await import(R + "index.ts")
const { BigDecimal, Cause, DateTime, Duration, Exit, Option, Redacted, Result } = await import(R + "index.ts")
const RpcMessage = await import("/Users/tylergibbs/pyfect-ref/effect/packages/effect/src/rpc/RpcMessage.ts")
const Int = Schema.Number.check(Schema.isInt())
const Person = Schema.Struct({ name: Schema.String, age: Schema.Number, active: Schema.Boolean, nickname: Schema.optionalKey(Schema.String) })
const Row = Schema.Struct({ id: Schema.String, label: Schema.String, tags: Schema.Array(Schema.String), attributes: Schema.Record(Schema.String, Schema.String), score: Schema.optionalKey(Schema.Number) })
const rows = [0,1,2,3].map((i) => ({ id: `row-${i}`, label: i % 2 ? "odd" : "even", tags: i % 2 ? ["blue"] : ["red","blue"], attributes: { region: "eu", worker: `w${i}` }, ...(i === 2 ? { score: 1.5 } : {}) }))
const Tagged = Schema.Union([Schema.Struct({ _tag: Schema.Literal("A"), n: Schema.Number }), Schema.Struct({ _tag: Schema.Literal("B"), text: Schema.String })])
const Mixed = Schema.Union([Schema.String, Schema.Number, Schema.Struct({ n: Schema.Boolean })])
const Natives = Schema.Struct({
  option: Schema.Option(Schema.String), none: Schema.Option(Schema.String), result: Schema.Result(Schema.Number, Schema.String),
  big: Schema.BigInt, bytes: Schema.Uint8Array, when: Schema.DateTimeUtc, zoned: Schema.DateTimeZoned, offset: Schema.DateTimeZoned,
  duration: Schema.Duration, decimal: Schema.BigDecimal, secret: Schema.Redacted(Schema.String), json: Schema.Unknown
})
const natives = {
  option: Option.some("x"), none: Option.none(), result: Result.fail("boom"), big: -(2n ** 70n), bytes: Uint8Array.of(1,2,3),
  when: DateTime.makeUnsafe(1000), zoned: DateTime.makeZonedUnsafe(1000, { timeZone: "Europe/London" }), offset: DateTime.makeZonedUnsafe(1000, { timeZone: 3600000 }),
  duration: Duration.nanos(1500000000n), decimal: BigDecimal.make(123n, 2), secret: Redacted.make("hush"), json: { nested: [1, "two", true, null] }
}
const ExitSchema = Schema.Exit(Schema.Number, Schema.String, Schema.Unknown)
const CauseSchema = Schema.Cause(Schema.String, Schema.Unknown)
const cause = Cause.fromReasons([Cause.makeFailReason("boom"), Cause.makeInterruptReason(7), Cause.makeInterruptReason()])
const cases = {
  number_ints: [Schema.Array(Schema.Number), [0, 1, -1, 1000]],
  number_decimals: [Schema.Array(Schema.Number), [1.5, -0.25, 12.75]],
  number_floats: [Schema.Array(Schema.Number), [1, Math.PI, 1e300]],
  int_array: [Schema.Array(Int), [1, -2, 3]],
  person: [Person, { name: "Ada", age: 36, active: true }],
  person_decimal: [Person, { name: "Ada", age: 36.5, active: false, nickname: "A" }],
  rows: [Schema.Array(Row), rows],
  record: [Schema.Record(Schema.String, Schema.Number), { b: 2, a: 1, "é": 3 }],
  tagged_a: [Tagged, { _tag: "A", n: 1.5 }],
  tagged_b: [Tagged, { _tag: "B", text: "x" }],
  mixed_string: [Mixed, "x"], mixed_number: [Mixed, 1.5], mixed_struct: [Mixed, { n: true }],
  tuple: [Schema.Tuple([Schema.Boolean, Schema.String]), [true, "x"]],
  natives: [Natives, natives],
  exit_ok: [ExitSchema, Exit.succeed(42)],
  exit_cause: [ExitSchema, Exit.failCause(cause)],
  cause: [CauseSchema, cause],
  recursive: (() => { const Node = Schema.Struct({ v: Schema.Number, children: Schema.Array(Schema.suspend(() => Node)) }); return [Node, { v: 1, children: [{ v: 2, children: [] }, { v: 3, children: [] }] }] })(),
  field_id: [Schema.Struct({ n: Schema.Number.pipe(SchemaBinary.fieldId(7)), s: Schema.String.pipe(SchemaBinary.fieldId(200)) }), { n: 1, s: "x" }]
}
const hex = (b) => Buffer.from(b).toString("hex")
const out = {}
for (const [name, [schema, value]] of Object.entries(cases)) {
  out[name] = {
    default: hex(Schema.encodeUnknownSync(SchemaBinary.toCodec(schema))(value)),
    fingerprint: hex(Schema.encodeUnknownSync(SchemaBinary.toCodec(schema, { fingerprint: true }))(value)),
  }
}
// dictionary stream
const Message = Schema.Struct({ tag: Schema.String, traceId: Schema.String, body: Schema.String, n: Schema.Number })
const dict = SchemaBinary.encoder(Message, { dictionary: true })
out.dictionary = [0,1,2,3,4].map((i) => hex(dict.encode({ tag: ["Search","Get","Delete"][i % 3], traceId: "0123456789abcdef0123456789abcdef", body: `body ${i % 2}`, n: i })))
const many = SchemaBinary.encodeManyUnknownSync(Person)
out.many = hex(many([{ name: "Ada", age: 36, active: true }, { name: "Grace", age: 45, active: false }]))
// rpc envelope
const enc = SchemaBinary.encoder(RpcMessage.EncodedSchema, { fingerprint: true })
const payload = Uint8Array.of(9, 8)
out.rpc = {
  request: hex(enc.encode({ _tag: "Request", id: "1", tag: "Get", payload, headers: [["a", "b"]] })),
  request_full: hex(enc.encode({ _tag: "Request", id: 7, tag: "Get", payload, headers: [], isNotification: true, traceId: "t", spanId: "s", sampled: true })),
  ack: hex(enc.encode({ _tag: "Ack", requestId: "1" })),
  interrupt: hex(enc.encode({ _tag: "Interrupt", requestId: 7 })),
  ping: hex(enc.encode({ _tag: "Ping" })),
  eof: hex(enc.encode({ _tag: "Eof" })),
  chunk: hex(enc.encode({ _tag: "Chunk", requestId: "1", values: payload })),
  exit: hex(enc.encode({ _tag: "Exit", requestId: "1", exit: payload })),
  defect: hex(enc.encode({ _tag: "Defect", defect: payload })),
  pong: hex(enc.encode({ _tag: "Pong" })),
}
// parity bugs found by comparing against Effect
const recursiveOf = (value) => { const Node = Schema.Struct({ v: value, children: Schema.Array(Schema.suspend(() => Node)) }); return Node }
const OptRec = recursiveOf(Schema.Number)
const both = (schema, value) => ({
  default: hex(Schema.encodeUnknownSync(SchemaBinary.toCodec(schema))(value)),
  fingerprint: hex(Schema.encodeUnknownSync(SchemaBinary.toCodec(schema, { fingerprint: true }))(value)),
})
out.parity = {
  recursive_redacted: both(recursiveOf(Schema.Redacted(Schema.String)), { v: Redacted.make("x"), children: [] }),
  optional_recursive: both(Schema.Struct({ parent: Schema.optionalKey(OptRec), n: Schema.Number }), { parent: { v: 1, children: [] }, n: 2 }),
  redacted_recursive: both(Schema.Redacted(OptRec), Redacted.make({ v: 1, children: [] })),
  zoned_offset_zero_in_union: both(Schema.Union([Schema.DateTimeZoned, Schema.Number]), DateTime.makeZonedUnsafe(1000, { timeZone: 0 })),
  wide_number_in_union: both(Schema.NullOr(Schema.Number), 2 ** 53),
  redacted_same_member: both(Schema.Union([Schema.String, Schema.Redacted(Schema.String)]), "x"),
  optional_tuple_element: both(Schema.Tuple([Schema.String, Schema.optionalKey(Schema.String)]), ["a", "b"]),
}
const optionalPair = SchemaBinary.encoder(Schema.Struct({ a: Schema.optionalKey(Schema.String), b: Schema.optionalKey(Schema.String), c: Schema.String }), { dictionary: true })
out.optional_dictionary = [{ a: "shared", c: "other" }, { b: "shared", c: "shared" }, { a: "shared", c: "shared" }, { b: "shared", c: "shared" }].map((v) => hex(optionalPair.encode(v)))
// event log frames
const { EventLogMessage } = await import(R + "eventlog/index.ts")
const entryId = (n) => Uint8Array.from(Buffer.from(n, "hex"))
const id1 = entryId("018f4a1e7b0070008000000000000001"), remote = entryId("0102030405060708090a0b0c0d0e0f10")
const encode = (schema, value) => hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(schema))(value))
const batch = { entryIds: [id1], iv: Uint8Array.of(1, 2), encryptedBatch: Uint8Array.of(3, 4) }
out.eventlog = {
  hello: encode(EventLogMessage.HelloResponse, new EventLogMessage.HelloResponse({ remoteId: remote, challenge: Uint8Array.of(5), firstSequence: 3 })),
  hello_no_sequence: encode(EventLogMessage.HelloResponse, new EventLogMessage.HelloResponse({ remoteId: remote, challenge: Uint8Array.of(5) })),
  authenticate: encode(EventLogMessage.Authenticate, new EventLogMessage.Authenticate({ publicKey: "pk", signingPublicKey: Uint8Array.of(6), signature: Uint8Array.of(7), algorithm: "Ed25519" })),
  write_ack: encode(EventLogMessage.WriteAck, { entryId: id1, sequence: 9 }),
  changes_payload: encode(EventLogMessage.ChangesRpc.payloadSchema, { publicKey: "pk", storeId: "s", startSequence: 2 }),
  protocol_error: encode(EventLogMessage.EventLogProtocolError, new EventLogMessage.EventLogProtocolError({ requestTag: "T", code: "NotFound", message: "m", publicKey: "pk" })),
  protocol_error_bare: encode(EventLogMessage.EventLogProtocolError, new EventLogMessage.EventLogProtocolError({ requestTag: "T", code: "NotFound", message: "m" })),
  write_encrypted: hex(Schema.encodeUnknownSync(EventLogMessage.WriteEntries.FromSchemaBinary)(new EventLogMessage.WriteEntries({ publicKey: "pk", storeId: "s", batches: [batch] }))),
  changes_encrypted: hex(Schema.encodeUnknownSync(EventLogMessage.ChangesRpc.EncryptedFromSchemaBinary)([{ ...batch, sequence: 4 }])),
}
// cluster envelopes and replies with every optional part
const { Headers } = await import(R + "http/index.ts")
const { Envelope, EntityAddress, EntityId, EntityType, Reply, ShardId, Snowflake } = await import(R + "cluster/index.ts")
const address = new EntityAddress.EntityAddress({ shardId: ShardId.make("default", 7), entityType: EntityType.make("Thing"), entityId: EntityId.make("e1") })
const partial = (value) => hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(Envelope.Partial))(value))
const ReplyExit = Schema.Exit(Schema.Number, Schema.String, Schema.Defect())
const replySchema = Schema.Union([Reply.WithExit.schemaFrom(ReplyExit), Reply.Chunk.schemaFrom(Schema.Number)])
out.cluster = {
  request_traced: partial({ _tag: "Request", requestId: Snowflake.Snowflake("123"), address, tag: "Inc", payload: Uint8Array.of(1), headers: Headers.fromInput({ "x-a": "b" }), traceId: "t", spanId: "s", sampled: true }),
  reply_exit: hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(replySchema))(new Reply.WithExit({ requestId: Snowflake.Snowflake("5"), id: Snowflake.Snowflake("6"), exit: Exit.succeed(1) }))),
  reply_chunk: hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(replySchema))(new Reply.Chunk({ requestId: Snowflake.Snowflake("5"), id: Snowflake.Snowflake("6"), sequence: 2, values: [1, 2] }))),
}
const { ClusterError } = await import(R + "cluster/index.ts")
const errors = Schema.Union([ClusterError.EntityNotAssignedToRunner, ClusterError.MailboxFull, ClusterError.AlreadyProcessingMessage])
const errorFrame = (value) => hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(errors))(value))
out.cluster.already_processing = errorFrame(new ClusterError.AlreadyProcessingMessage({ envelopeId: Snowflake.Snowflake("5"), address }))
out.cluster.mailbox_full = errorFrame(new ClusterError.MailboxFull({ address }))
const Cron = Schema.Struct({ dateTime: Schema.DateTimeUtc, executor: Schema.optional(Schema.Boolean) })
const cronAt = DateTime.makeUnsafe(1000)
out.cluster.cron = hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(Cron))({ dateTime: cronAt, executor: true }))
const Parent = Schema.optional(Schema.Struct({ workflowName: Schema.String, executionId: Schema.String, detached: Schema.optional(Schema.Boolean) }))
out.cluster.workflow_run = hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(Schema.Struct({ n: Schema.Number, "~effect/cluster/ClusterWorkflowEngine/payloadParentKey": Parent })))({ n: 1, "~effect/cluster/ClusterWorkflowEngine/payloadParentKey": { workflowName: "w", executionId: "e", detached: true } }))
out.cluster.resume = hex(Schema.encodeUnknownSync(SchemaBinary.toCodecDirect(Schema.Struct({ childExecutionId: Schema.optional(Schema.String) })))({ childExecutionId: "c" }))
// union members Python's guards could confuse, and the dictionary's limits
out.parity.rank_zoned = both(Schema.Union([Schema.DateTimeZoned, Schema.DateTimeUtc]), DateTime.makeUnsafe(1000))
out.parity.rank_bigint = both(Schema.Union([Schema.BigInt, Schema.Number]), 1)
out.parity.rank_unknown = both(Schema.Union([Schema.Unknown, Schema.String]), "x")
const { createHash } = await import("node:crypto")
const limitValue = (i) => `value-${i}`
const limitHash = createHash("sha256")
const referencing = SchemaBinary.encoder(Schema.String, { dictionary: true })
for (const i of [...Array(63).keys(), 0, ...Array.from({ length: 460 }, (_, k) => 63 + k), 511, 512, 0]) limitHash.update(referencing.encode(limitValue(i)))
const giveUp = SchemaBinary.encoder(Schema.String, { dictionary: true })
for (const i of [...Array(64).keys(), 0]) limitHash.update(giveUp.encode(limitValue(i)))
out.dictionary_limits = limitHash.digest("hex")
console.log(JSON.stringify(out, null, 1))
