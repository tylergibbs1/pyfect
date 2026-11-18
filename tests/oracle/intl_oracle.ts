// Effect's DateTime.format, formatUtc and formatLocal (Intl.DateTimeFormat) on the cases given
// as JSON on stdin, the oracle for tests/oracle/test_intl_differential.py:
//   node tests/oracle/intl_oracle.ts < CASES.json > ANSWERS.json
// A case is [function, epoch millis, zone, options]; its answer is the formatted string, or
// "!" and the error's name and message when Effect throws. Reads Effect's sources from
// $PYFECT_EFFECT_REF (the pinned checkout, tests/_effect_ref.py). Node 24 runs TypeScript.
import { readFileSync } from "node:fs"

const EFFECT = process.env.PYFECT_EFFECT_REF
if (!EFFECT) throw new Error("set PYFECT_EFFECT_REF=$(uv run python tests/_effect_ref.py), the pinned Effect checkout")
const DateTime = await import(`${EFFECT}/packages/effect/src/DateTime.ts`)

type Case = [string, number, string, Record<string, string>]

const answer = ([fn, millis, zone, options]: Case): string => {
  try {
    if (fn === "format") {
      return DateTime.format(DateTime.makeZonedUnsafe(millis, { timeZone: zone }), options)
    }
    const utc = DateTime.makeUnsafe(millis)
    return fn === "formatUtc" ? DateTime.formatUtc(utc, options) : DateTime.formatLocal(utc, options)
  } catch (error) {
    return `!${(error as Error).name}: ${(error as Error).message}`
  }
}

const cases: Array<Case> = JSON.parse(readFileSync(0, "utf8"))
process.stdout.write(
  JSON.stringify({
    node: process.versions.node,
    icu: process.versions.icu,
    cldr: process.versions.cldr,
    tz: process.versions.tz,
    answers: cases.map(answer),
  })
)
