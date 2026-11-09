// Node's URL and URLSearchParams on the web-platform-tests URL suite, the
// oracle for tests/oracle/test_whatwg_url.py:
//   node tests/oracle/url_oracle.ts > tests/oracle/fixtures/wpt_url/node_answers.json
// The fixtures next to it are web-platform-tests' url/resources files as of
// commit c7933d2a9d366abd89b46aa5a7c0e0f9ae984aba. Node 24 (ada 4.0.0).
import { readFileSync } from "node:fs"

const dir = new URL("./fixtures/wpt_url/", import.meta.url)
const load = (name: string) => JSON.parse(readFileSync(new URL(name, dir), "utf8")).filter((t: any) => typeof t !== "string")
const props = ["href", "protocol", "username", "password", "host", "hostname", "port", "pathname", "search", "hash", "origin"]
const parse = (input: string, base?: string | null) => {
  try {
    return base == null ? new URL(input) : new URL(input, base)
  } catch {
    return null
  }
}

// Where Node's answer differs from the suite's expectation (the test expects Node's).
const differences: Record<string, unknown> = {}
for (const t of load("urltestdata.json")) {
  const url = parse(t.input, t.base)
  const ok = t.failure ? url === null : url !== null && props.every((p) => !(p in t) || (url as any)[p] === t[p])
  if (!ok) differences[`urltestdata ${JSON.stringify([t.input, t.base])}`] = url?.href ?? null
}
const setters = JSON.parse(readFileSync(new URL("setters_tests.json", dir), "utf8"))
for (const [setter, cases] of Object.entries<any>(setters)) {
  if (setter === "comment") continue
  for (const c of cases) {
    const url = new URL(c.href)
    ;(url as any)[setter] = c.new_value
    if (!Object.entries(c.expected).every(([k, v]) => (url as any)[k] === v)) {
      differences[`setter ${JSON.stringify([setter, c.href, c.new_value])}`] = url.href
    }
  }
}
const host = (input: string) => parse(`https://${input}/x`)?.host ?? null
for (const name of ["toascii.json", "IdnaTestV2.json"]) {
  for (const t of load(name)) {
    if (host(t.input) !== t.output) differences[`${name} ${JSON.stringify(t.input)}`] = host(t.input)
  }
}

// URLSearchParams: WPT's urlencoded-parser inputs and more, and serializing
// every ASCII character and some beyond.
const parseInputs = [
  "test", "﻿test=﻿", "%EF%BB%BFtest=%EF%BB%BF", "%EF%BF%BF=%EF%BF%BF", "%FE%FF", "%FF%FE",
  "†&†=x", "%C2", "%C2x", "_charset_=windows-1252&test=%C2x", "", "a", "a=b", "a=", "=b", "&", "&a",
  "a&", "a&a", "a&b&c", "a=b&c=d", "a=b&c=d&", "&&&a=b&&&&c=d&", "a=a&a=b&a=c", "a==a", "a=a+b+c+d",
  "%=a", "%a=a", "%a_=a", "%61=a", "%61+%4d%4D=", "id=0&value=%", "b=%2sf%2a", "b=%2%2af%2a", "b=%%2a",
  "?a=b", "??a=b", "a=%F0%9F%98%80", "a=%ED%A0%80", "a=%E2%82", "a=\uD800", "a=\uDE00x", ";a=b;c",
  "a=b#c", "+=+", "%2B=%2b", "%20%zz%", "é=%C3%A9",
]
const formParse = parseInputs.map((input) => [input, [...new URLSearchParams(input)]])
const serializeInputs: Array<[string, string]> = []
for (let i = 0; i < 128; i++) serializeInputs.push([String.fromCharCode(i), "x"])
serializeInputs.push(["é", "€"], ["😀", "\uD800"], ["a b", "c+d"], ["", ""], ["\uDE00", "~*-._"])
const formSerialize = serializeInputs.map((pair) => [pair, new URLSearchParams([pair]).toString()])
const searchParams = [
  "https://a/?a=b&c", "https://a/??x=1", "https://a/?%zz=%F0%9F%98%80", "a:b?x=+y", "https://a/?",
].map((href) => [href, [...new URL(href).searchParams]])
const canParse = [
  [null, null], ["aaa:b", null], [null, "aaa:b"], [null, "https://test:test/"], ["aaa:/b", null],
  [null, "aaa:/b"], ["https://test:test", null], ["a", "https://b/"],
].map(([url, base]) => [url, base, URL.canParse(String(url), base === null ? undefined : base)])

console.log(JSON.stringify({ differences, formParse, formSerialize, searchParams, canParse }, null, 1))
