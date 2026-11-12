// Effect's own parsers on the fuzz inputs, the oracle for tests/fuzz/differential.py:
//   node tests/fuzz/effect_oracle.ts INPUTS.json > ANSWERS.json
// INPUTS.json is [[parser, text], ...]; each answer is what `answers` in differential.py
// computes in pyfect, as JSON (null where the parser rejects the text), run with TZ=UTC. Reads Effect's
// sources from $PYFECT_EFFECT_REF (an Effect 4.1.2 checkout). Node 24 runs TypeScript.
import { readFileSync } from "node:fs"

const R = `${process.env.PYFECT_EFFECT_REF}/packages/effect/src/`
const Base64 = await import(R + "encoding/Base64.ts")
const Base64Url = await import(R + "encoding/Base64Url.ts")
const Hex = await import(R + "encoding/Hex.ts")
const Json5 = await import(R + "encoding/Json5.ts")
const Jsonc = await import(R + "encoding/Jsonc.ts")
const Toml = await import(R + "encoding/Toml.ts")
const Yaml = await import(R + "encoding/Yaml.ts")
const Ini = await import(R + "encoding/Ini.ts")
const Duration = await import(R + "Duration.ts")
const Cron = await import(R + "Cron.ts")
const SemVer = await import(R + "SemVer.ts")
const SemVerRange = await import(R + "SemVerRange.ts")
const BigDecimal = await import(R + "BigDecimal.ts")
const ByteSize = await import(R + "ByteSize.ts")
const DateTime = await import(R + "DateTime.ts")
const Glob = await import(R + "Glob.ts")
const JsonPointer = await import(R + "JsonPointer.ts")
const Cookies = await import(R + "http/Cookies.ts")
const Option = await import(R + "Option.ts")
const Result = await import(R + "Result.ts")

const hex = (bytes: Uint8Array) => Buffer.from(bytes).toString("hex")
const ok = <A>(result: any, f: (a: A) => unknown) => (Result.isSuccess(result) ? f(result.success) : null)
const some = <A>(option: any, f: (a: A) => unknown) => (Option.isSome(option) ? f(option.value) : null)
const thrown = (f: () => unknown) => {
  try {
    return f()
  } catch {
    return null
  }
}
// JSON.parse(JSON.stringify(value)), a BigInt as a tagged string.
const json = (value: unknown) =>
  JSON.parse(JSON.stringify(value, (_key, v) => (typeof v === "bigint" ? `bigint:${v}` : v)))
const START = Date.UTC(2024, 2, 10, 1, 30)

const answers: Record<string, (text: string) => unknown> = {
  base64: (t) => ok(Base64.decode(t), hex),
  base64url: (t) => ok(Base64Url.decode(t), hex),
  hex: (t) => ok(Hex.decode(t), hex),
  json5: (t) => ok(Json5.parse(t), json),
  jsonc: (t) => ok(Jsonc.parse(t), json),
  toml: (t) => ok(Toml.parse(t), json),
  yaml: (t) => thrown(() => json(Yaml.parse(t))),
  ini: (t) => thrown(() => json(Ini.parse(t))),
  duration: (t) =>
    some(Duration.fromInput(t), (d: any) => some(Duration.toNanos(d), String) ?? "infinity"),
  duration_iso: (t) =>
    some(Duration.fromIso(t), (d: any) => some(Duration.toNanos(d), String) ?? "infinity"),
  cron: (t) =>
    ok(Cron.parse(t), (c: any) => [Cron.format(c), thrown(() => Cron.next(c, START).getTime())]),
  semver: (t) => ok(SemVer.parse(t), SemVer.format),
  semver_range: (t) => ok(SemVerRange.parse(t), SemVerRange.format),
  big_decimal: (t) => some(BigDecimal.fromString(t), BigDecimal.format),
  byte_size: (t) => some(ByteSize.fromString(t), String),
  zone: (t) => some(DateTime.zoneFromString(t), DateTime.zoneToString),
  zoned: (t) => some(DateTime.makeZonedFromString(t), DateTime.formatIsoZoned),
  glob: (t) => {
    // Python's partition: the path is everything after the first newline.
    const at = t.indexOf("\n")
    const [pattern, path] = at === -1 ? [t, ""] : [t.slice(0, at), t.slice(at + 1)]
    return thrown(() => Glob.match(Glob.make(pattern), path))
  },
  pointer: (t) => JsonPointer.parseUriFragment(t) ?? null,
  cookies: (t) => Cookies.parseHeader(t),
}

const inputs: Array<[string, string]> = JSON.parse(readFileSync(process.argv[2], "utf8"))
console.log(JSON.stringify(inputs.map(([parser, text]) => thrown(() => answers[parser](text)) ?? null)))
