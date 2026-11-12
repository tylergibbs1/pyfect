// Effect's DateTime.format, formatUtc and formatLocal (Intl.DateTimeFormat) on the cases given
// as JSON on stdin, the oracle for tests/oracle/test_intl_differential.py:
//   node tests/oracle/intl_oracle.ts < CASES.json > ANSWERS.json
// A case is [function, epoch millis, zone, options]; its answer is the formatted string, or
// "!" and the error's name and message when Effect throws. Reads Effect's sources from
// $PYFECT_EFFECT_REF (an Effect 4.1.2 checkout). Node 24 runs TypeScript.
import { readFileSync } from "node:fs"

const DateTime = await import(`${process.env.PYFECT_EFFECT_REF}/packages/effect/src/DateTime.ts`)

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
