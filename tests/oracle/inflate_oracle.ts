// Effect's inflater and Zip.decode on the streams of _inflate_corpus.py, under Node:
//   uv run python tests/oracle/_inflate_corpus.py > corpus.json
//   node tests/oracle/inflate_oracle.ts corpus.json > tests/oracle/fixtures/inflate_oracle.json
// Each case keeps its input; "raw" pushes the splits one per NeedInput, "bytewise" one
// byte per NeedInput (so "pushes" is the byte at which the stream fails), "zip" reads
// the stream as entry "f" of a zip archive pulled in chunks of zipSplits.
import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"

const R = "/Users/tylergibbs/pyfect-ref/effect/packages/effect/src/"
const { Effect, Exit, Stream } = await import(R + "index.ts")
const Zip = await import(R + "encoding/Zip.ts")
const { ByteQueue, Inflater, InflateMemory, NeedInput } = await import(R + "internal/inflate.ts")

const hash = (d: Uint8Array) => `${d.length}:${createHash("sha256").update(d).digest("hex").slice(0, 12)}`
// A list of chunk hashes, as its length and a hash of it
const sequence = (hashes: Array<string>) =>
  `${hashes.length}:${createHash("sha256").update(hashes.join(",")).digest("hex").slice(0, 12)}`
const bytes = (b64: string) => new Uint8Array(Buffer.from(b64, "base64"))
const le = (n: number, size: number) => Array.from({ length: size }, (_, i) => Math.floor(n / 2 ** (8 * i)) & 0xff)

const local = (name: number, method: number, crc: number, compressed: number, size: number) =>
  [0x50, 0x4b, 3, 4, ...le(20, 2), 0, 0, ...le(method, 2), 0, 0, 0x21, 0, ...le(crc, 4), ...le(compressed, 4), ...le(size, 4), 1, 0, 0, 0, name]

const zipArchive = (data: Uint8Array, crc: number, size: number) =>
  Uint8Array.from([
    ...local(0x66, 8, crc, data.length, size),
    ...data,
    ...local(0x67, 0, 0x042f103c, 4, 4),
    ...Buffer.from("next"),
    0x50, 0x4b, 5, 6, ...Array(18).fill(0)
  ])

const raw = (data: Uint8Array, splits: Array<number>) => {
  const queue = new ByteQueue()
  const inflater = new Inflater(queue, new InflateMemory())
  let at = 0
  let pushes = 0
  const outs: Array<string> = []
  while (true) {
    let r: any
    try {
      r = inflater.pull()
    } catch (e: any) {
      return { outs: sequence(outs), pushes, error: e.message }
    }
    if (r === NeedInput) {
      if (pushes === splits.length) return { outs: sequence(outs), pushes, end: "truncated" }
      queue.push(data.subarray(at, at + splits[pushes]))
      at += splits[pushes]
      pushes++
      continue
    }
    if (r === undefined) return { outs: sequence(outs), pushes, end: "done", left: queue.length + data.length - at }
    outs.push(hash(r))
  }
}

const archive = async (data: Uint8Array, splits: Array<number>) => {
  const chunks: Array<Uint8Array> = []
  let at = 0
  for (const s of splits) {
    chunks.push(data.subarray(at, at + s))
    at += s
  }
  const items: Array<any> = []
  let pulls = 0
  const effect = Stream.fromIterable(chunks, { chunkSize: 1 }).pipe(
    Stream.tap(() => Effect.sync(() => void pulls++)),
    Stream.pipeThroughChannel(Zip.decode()),
    Stream.mapEffect((entry: any) => {
      const record: any = { path: entry.header.path, chunks: [] }
      items.push(record)
      return Stream.runForEach(entry.body, (c: Uint8Array) => Effect.sync(() => void record.chunks.push(hash(c))))
    }),
    Stream.runDrain
  )
  const exit: any = await Effect.runPromiseExit(effect)
  for (const item of items) item.chunks = sequence(item.chunks)
  if (Exit.isSuccess(exit)) return { items, error: null, pulls }
  const failure = exit.cause.reasons.find((r: any) => r._tag === "Fail")
  return { items, error: { kind: failure.error.kind, message: failure.error.message }, pulls }
}

const cases = JSON.parse(readFileSync(process.argv[2]!, "utf8"))
for (const c of cases) {
  const data = bytes(c.data)
  c.raw = raw(data, c.splits)
  c.bytewise = data.length <= 3000 ? raw(data, Array(data.length).fill(1)) : null
  c.zip = await archive(zipArchive(data.subarray(0, c.compressed), c.crc, c.size), c.zipSplits)
}
process.stdout.write(JSON.stringify(cases) + "\n")
