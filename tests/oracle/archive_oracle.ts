// Effect's Xml, Tar and Zip on the corpus of _archive_corpus.py, under Node:
//   uv run python tests/oracle/_archive_corpus.py > corpus.json
//   node tests/oracle/archive_oracle.ts corpus.json > tests/oracle/fixtures/archive_oracle.json
import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"

const R = "/Users/tylergibbs/pyfect-ref/effect/packages/effect/src/"
const { Effect, Exit, Stream } = await import(R + "index.ts")
const Xml = await import(R + "encoding/Xml.ts")
const Tar = await import(R + "encoding/Tar.ts")
const Zip = await import(R + "encoding/Zip.ts")

const bytes = (b64: string) => new Uint8Array(Buffer.from(b64, "base64"))
const digest = (data: Uint8Array) => `${data.length}:${createHash("sha256").update(data).digest("hex").slice(0, 16)}`
const date = (ms: any) => (ms === "invalid" ? new Date(NaN) : ms === null || ms === undefined ? undefined : new Date(ms))
const defined = (o: any) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined))

const header = (h: any) =>
  defined({
    ...h,
    mtime: h.mtime.getTime(),
    linkTarget: h.linkTarget ?? null,
    devMajor: h.devMajor ?? null,
    devMinor: h.devMinor ?? null,
    size: h.size ?? null,
    mode: h.mode ?? null
  })

const concat = (chunks: Array<Uint8Array>) => {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0))
  let at = 0
  for (const c of chunks) {
    out.set(c, at)
    at += c.length
  }
  return out
}

// Items produced, then how the stream ended
const collect = async (stream: any, onItem: (item: any) => any = Effect.succeed) => {
  const items: Array<unknown> = []
  const effect = stream.pipe(
    Stream.mapEffect(onItem),
    Stream.runForEach((item: unknown) => Effect.sync(() => void items.push(item)))
  )
  const exit: any = await Effect.runPromiseExit(effect)
  if (Exit.isSuccess(exit)) return { items, error: null }
  const failure = exit.cause.reasons.find((r: any) => r._tag === "Fail")
  if (failure === undefined) return { items, die: true }
  const e = failure.error
  return { items, error: defined({ kind: e.kind, message: e.message, line: e.line, column: e.column }) }
}

// A body failure ends the archive; report the header before it, with no body
const decodeEntriesStrict = async (channel: any, chunks: any) => {
  const items: Array<unknown> = []
  const stream = Stream.fromIterable(chunks, { chunkSize: 1 }).pipe(Stream.pipeThroughChannel(channel))
  const effect = stream.pipe(
    Stream.mapEffect((entry: any) => {
      const record: any = { header: header(entry.header), body: null }
      items.push(record)
      return Effect.map(Stream.runCollect(entry.body), (body: any) => {
        record.body = digest(concat(body))
      })
    }),
    Stream.runDrain
  )
  const exit: any = await Effect.runPromiseExit(effect)
  if (Exit.isSuccess(exit)) return { items, error: null }
  const failure = exit.cause.reasons.find((r: any) => r._tag === "Fail")
  if (failure === undefined) return { items, die: true }
  return { items, error: { kind: failure.error.kind, message: failure.error.message } }
}

const tarEntry = (e: any) => {
  const options = defined({
    mode: e.mode,
    uid: e.uid,
    gid: e.gid,
    uname: e.uname,
    gname: e.gname,
    mtime: date(e.mtime),
    pax: e.pax
  })
  switch (e.kind) {
    case "file":
      return Tar.file(e.path, e.text ?? bytes(e.content), options)
    case "stream":
      return Tar.fileStream(e.path, e.size, Stream.fromIterable(e.chunks.map(bytes)), options)
    case "directory":
      return Tar.directory(e.path, options)
    case "symlink":
      return Tar.symlink(e.path, e.target, options)
    case "hardlink":
      return Tar.hardlink(e.path, e.target, options)
    default: {
      const { header: h } = Tar.file(e.path, "", options)
      return {
        header: { ...h, type: e.type, typeflag: e.typeflag, size: e.size ?? 0, devMajor: e.devMajor, devMinor: e.devMinor },
        body: Stream.empty
      }
    }
  }
}

const zipEntry = (e: any) => {
  const options = defined({ method: e.method, mode: e.mode, mtime: date(e.mtime) })
  switch (e.kind) {
    case "file":
      return Zip.file(e.path, e.text ?? bytes(e.content), options)
    case "stream":
      return Zip.fileStream(e.path, Stream.fromIterable(e.chunks.map(bytes)), defined({ ...options, size: e.size }))
    default:
      return Zip.directory(e.path, options)
  }
}

const encoded = async (stream: any) => {
  const chunks: Array<Uint8Array> = []
  const result: any = await collect(
    stream.pipe(Stream.map((c: Uint8Array) => (chunks.push(c), null))),
    Effect.succeed
  )
  const { items: _, ...rest } = result
  return { ...rest, bytes: digest(concat(chunks)) }
}

const xmlEvent = (e: any) => {
  if (e._tag === "StartElement") return { ...e, attributes: e.attributes }
  return defined(e)
}

const run = async (c: any) => {
  const chunks = (c.chunks ?? []).map(bytes)
  switch (c.op) {
    case "tar.decode":
      return decodeEntriesStrict(Tar.decode(), chunks)
    case "zip.decode":
      return decodeEntriesStrict(Zip.decode(), chunks)
    case "tar.encode":
      return encoded(Stream.fromIterable(c.entries.map(tarEntry)).pipe(Stream.pipeThroughChannel(Tar.encode())))
    case "zip.encode":
      return encoded(Stream.fromIterable(c.entries.map(zipEntry)).pipe(Stream.pipeThroughChannel(Zip.encode())))
    case "xml.decode":
      return collect(
        Stream.fromIterable(chunks, { chunkSize: 1 }).pipe(Stream.pipeThroughChannel(Xml.decode(c.options)), Stream.map(xmlEvent))
      )
    case "xml.decodeString":
      return collect(
        Stream.fromIterable(c.strings, { chunkSize: 1 }).pipe(Stream.pipeThroughChannel(Xml.decodeString(c.options)), Stream.map(xmlEvent))
      )
    case "xml.elements":
      return collect(
        Stream.fromIterable(c.events, { chunkSize: 1 }).pipe(Stream.pipeThroughChannel(Xml.elements(c.path, c.options)))
      )
    case "xml.encodeString":
      return collect(Stream.fromIterable(c.events).pipe(Stream.pipeThroughChannel(Xml.encodeString())))
  }
  throw new Error(`unknown op ${c.op}`)
}

const corpus = JSON.parse(readFileSync(process.argv[2]!, "utf8"))
const out: Record<string, unknown> = {}
for (const c of corpus) out[c.id] = await run(c)
process.stdout.write(JSON.stringify(out, null, 0) + "\n")
