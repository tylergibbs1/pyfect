// JavaScript's Date.parse on a corpus of strings, under Node in two zones:
//   node tests/oracle/js_date_oracle.ts tests/oracle/fixtures/js_date_parse.json > new.json
// The input is a JSON list of strings, or the fixture itself (its first
// column is read back, so strings are added by appending [text] rows).
// Each row is [text, Date.parse with TZ=UTC, with TZ=America/New_York],
// null for an Invalid Date.
import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"

const ZONES = ["UTC", "America/New_York"]

if (process.argv[3] === "--parse") {
  const texts: Array<string> = JSON.parse(readFileSync(process.argv[2], "utf8"))
  const parsed = texts.map((text) => Date.parse(text))
  process.stdout.write(JSON.stringify(parsed.map((ms) => (Number.isNaN(ms) ? null : ms))))
} else {
  const input: Array<string | Array<unknown>> = JSON.parse(readFileSync(process.argv[2], "utf8"))
  const texts = input.map((row) => (typeof row === "string" ? row : (row[0] as string)))
  const tmp = `${process.env.TMPDIR ?? "/tmp"}/js_date_texts_${process.pid}.json`
  const { writeFileSync, rmSync } = await import("node:fs")
  writeFileSync(tmp, JSON.stringify(texts))
  const columns = ZONES.map((zone) =>
    JSON.parse(
      execFileSync(process.execPath, [process.argv[1], tmp, "--parse"], {
        env: { ...process.env, TZ: zone },
        encoding: "utf8"
      })
    )
  )
  rmSync(tmp)
  const rows = texts.map((text, i) => JSON.stringify([text, ...columns.map((column) => column[i])]))
  process.stdout.write("[\n" + rows.join(",\n") + "\n]\n")
}
