// Records every path.win32 / path.posix call Node's own path tests make, plus extra cases,
// with the result Node gives: the fixture tests/oracle/fixtures/node_path_cases.json.
//
//   node tests/oracle/node_path/oracle.cjs tests/oracle/node_path/test/parallel \
//     > tests/oracle/fixtures/node_path_cases.json
//
// test/parallel holds Node's test-path-*.js for the Node version the fixture records
// (refetch them with scripts/fetch_node_path_tests.sh when moving to another). Each test file
// runs in its own process with process.cwd() fixed at "/work/dir" (the extra per-drive cases
// use "C:\work\dir"); each case records the cwd and "=X:" drive variables it ran with.
"use strict"
const { execFileSync } = require("node:child_process")
const fs = require("node:fs")
const path = require("node:path")

const POSIX_CWD = "/work/dir"
const WIN32_CWD = "C:\\work\\dir"
const METHODS = [
  "resolve", "normalize", "isAbsolute", "join", "relative", "toNamespacedPath",
  "dirname", "basename", "extname", "format", "parse",
]

function record(cases, platform, name, args, cwd, driveCwds, result) {
  cases.push({ platform, name, args, cwd, drive_cwds: driveCwds, result })
}

function instrument(cases) {
  let depth = 0
  let cwd = POSIX_CWD
  process.cwd = () => cwd
  for (const platform of ["win32", "posix"]) {
    const ns = path[platform]
    for (const name of METHODS) {
      const original = ns[name]
      ns[name] = function (...args) {
        const ok = args.every((a) => typeof a === "string" || (name === "format" && a && typeof a === "object")) &&
          (args.length > 0 || name === "join" || name === "resolve")
        // Only calls the tests make, not Node's module loader.
        const fromTest = /test-path[^/]*\.js:|extraCases/.test(new Error().stack.split("\n")[2] ?? "")
        if (!ok || depth > 0 || !fromTest) return original.apply(this, args)
        depth++
        try {
          const result = original.apply(this, args)
          const driveCwds = Object.fromEntries(Object.entries(process.env).filter(([k]) => /^=[A-Za-z]:$/.test(k)))
          record(cases, platform, name, args, process.cwd(), driveCwds, result)
          return result
        } finally {
          depth--
        }
      }
    }
  }
  return {
    setCwd(value) { cwd = value },
  }
}

function extraCases(control) {
  const w = path.win32
  const p = path.posix
  // Per-drive working directories (Windows keeps them in "=X:" variables), from a Windows cwd.
  control.setCwd(WIN32_CWD)
  // A POSIX host's environment refuses names with "=", so the variables go on a plain object.
  const env = process.env
  process.env = { ...env, "=D:": "D:\\dcwd\\sub", "=E:": "C:\\elsewhere", "=F:": "f:no-separator" }
  for (const args of [
    ["D:"], ["D:a"], ["d:a\\..\\.."], ["E:x"], ["F:y"], ["G:z"], ["C:x"], ["c:"], ["C:"],
    ["D:a", "b"], ["c:/x", "D:y"], ["\\x", "D:y"], ["D:", "\\x"], ["//server/share", "D:y"],
  ]) w.resolve(...args)
  for (const [a, b] of [["D:a", "D:b"], ["D:", "C:\\work"], ["E:x", "C:\\elsewhere"]]) w.relative(a, b)
  for (const a of ["D:a", "E:x", "c", "C:", "D:"]) w.toNamespacedPath(a)
  process.env = env
  for (const a of ["", "x", "D:x", "\\x"]) w.resolve(a)
  control.setCwd(POSIX_CWD)
  for (const a of ["", ".", "x", "C:", "C:x", "\\", "\\\\?\\x", "\\\\.\\pipe\\p", "//a//b//c", "C:\\a\\..\\..\\b"]) {
    w.resolve(a)
    w.toNamespacedPath(a)
  }
  for (const a of [
    "", "\\", "/", "C:", "C:\\", "C:/", "C:..", "C:\\..", "c:a:b", "a:b", "a:", ":a", "a/b:c/d",
    "\\\\server", "\\\\server\\", "\\\\server\\share", "\\\\server\\share\\", "//server//share//x",
    "\\\\.\\COM1:", "\\\\?\\COM1:\\x", "\\\\?\\c:\\x\\..\\y", "\\\\.\\pipe\\a\\..\\b", "CON", "con:x",
    "COM\u00b9:", "lpt\u00b3:a", "x\\..\\..\\C:y", "a\\..\\b:c", "a\\..\\b:\\c", "\\\\\\x", "..\\a:b",
    "C:a\\..\\..", "\\a\\..\\..", "a\\.\\\\b\\", "\u0130\\..\\x", "\ud801\udc00\\a\\..",
  ]) {
    w.normalize(a)
    w.dirname(a)
    w.basename(a)
    w.extname(a)
    w.parse(a)
    w.isAbsolute(a)
  }
  for (const args of [
    [], [""], ["C:"], ["C:", "x"], ["\\", "x"], ["\\\\", "x"], ["\\\\\\", "x"], ["\\\\x"], ["\\\\x", "y"],
    ["//", "/", "x"], ["a", "COM1:", "b"], ["a/b", "AUX:/c"], ["C:", "..", "x"], ["", "\\\\a", "b"],
  ]) w.join(...args)
  for (const [a, b] of [
    ["C:\\a", "c:\\A\\b"], ["C:\\", "C:\\"], ["\\\\a\\b", "\\\\a\\b\\"], ["C:\\a\\b", "C:\\a\\B\\c"],
    ["C:\\\u0130", "c:\\i\u0307"], ["C:\\\u0130\\x", "C:\\\u0130\\y"], ["\\\\a\\b\\c", "\\\\a\\B"], ["C:\\ab", "C:\\a"],
    ["x", "y"], ["", ""], ["C:\\a", "D:\\a"],
  ]) w.relative(a, b)
  for (const a of ["C:\\x", "D:/y", "\\\\s\\h\\f", "//s/h", "\\\\?\\UNC\\s\\h", "\\\\.\\x", "C:", "\\\\?\\c:\\Windows/System"]) {
    w.toNamespacedPath(a)
  }
  for (const o of [
    { root: "C:\\", name: "a", ext: "b" }, { dir: "C:\\x", base: "y" }, { root: "\\\\s\\h\\", base: "f" },
    { name: "x", ext: ".y" }, { ext: "y" }, { dir: "d", root: "r", name: "n" }, {},
  ]) {
    w.format(o)
    p.format(o)
  }
  for (const a of [
    "", "/", "//", "///", "a//b", "/a/b/../../..", "a/./b/", "./", "../", "a/..", "/..", ".", "..",
    "\\x", "a\\..\\b", "/a.b/c.", "/.d", "...", "a.b.c", "/x/y.z/", "C:\\x",
  ]) {
    p.normalize(a)
    p.dirname(a)
    p.basename(a)
    p.extname(a)
    p.parse(a)
    p.isAbsolute(a)
    p.resolve(a)
    p.toNamespacedPath(a)
  }
  for (const args of [[], [""], ["/a", "b", "/c", "d"], ["a", "..", ".."], ["/", "..", "x"], ["//a"]]) {
    p.join(...args)
    p.resolve(...args)
  }
  for (const [a, b] of [["a", "b"], ["", "/x"], ["/x", ""], ["/a/b", "/a/bc"], ["/", "/"]]) p.relative(a, b)
  for (const [a, s] of [["a.js", ".js"], ["/x/a.js/", ".js"], ["aj", "j"], ["/a/b", "/b"], ["C:x.js", ".js"], ["C:", "C:"], ["C:\\", ":\\"]]) {
    p.basename(a, s)
    w.basename(a, s)
  }
}

// Node's test/common invalidArgTypeHelper.
function invalidArgTypeHelper(input) {
  const { inspect } = require("node:util")
  if (input == null) return ` Received ${input}`
  if (typeof input === "function") return ` Received function ${input.name}`
  if (typeof input === "object") {
    if (input.constructor?.name) return ` Received an instance of ${input.constructor.name}`
    return ` Received ${inspect(input, { depth: -1 })}`
  }
  let inspected = inspect(input, { colors: false })
  if (inspected.length > 28) inspected = `${inspected.slice(0, 25)}...`
  return ` Received type ${typeof input} (${inspected})`
}

function runOne(file) {
  const cases = []
  const control = instrument(cases)
  const Module = require("node:module")
  const realResolve = Module._resolveFilename
  Module._resolveFilename = function (request, ...rest) {
    if (request === "../common") return __filename + "#common"
    if (request === "../common/fixtures") return __filename + "#fixtures"
    return realResolve.call(this, request, ...rest)
  }
  require.cache[__filename + "#common"] = {
    id: "common", filename: "common", loaded: true,
    exports: { isWindows: false, skip() {}, invalidArgTypeHelper },
  }
  require.cache[__filename + "#fixtures"] = {
    id: "fixtures", filename: "fixtures", loaded: true, exports: { path: (...p) => path.join("/fixtures", ...p) },
  }
  if (file === "extra") extraCases(control)
  else require(file)
  process.stdout.write(JSON.stringify(cases))
}

function main() {
  let dir = process.argv[2]
  dir = path.resolve(dir)
  const files = fs.readdirSync(dir).filter((f) => /^test-path.*\.js$/.test(f) && f !== "test-path-glob.js").sort()
  const all = []
  const seen = new Set()
  for (const file of [...files.map((f) => path.join(dir, f)), "extra"]) {
    const out = execFileSync(process.execPath, [__filename, "--one", file], { maxBuffer: 1 << 28 })
    for (const c of JSON.parse(out)) {
      const text = JSON.stringify([c.platform, c.name, c.args, c.cwd, c.drive_cwds])
      // Calls on the test file's own name depend on where it was run from.
      const local = (t) => t.includes("test-path-") || t.includes(__dirname)
      if (seen.has(text) || local(text) || local(JSON.stringify(c.result))) continue
      seen.add(text)
      all.push(c)
    }
  }
  const header = { node: process.versions.node, tests: files }
  process.stdout.write(JSON.stringify({ ...header, cases: all }, null, 0).replace(/\},\{"platform"/g, '},\n{"platform"') + "\n")
}

if (process.argv[2] === "--one") runOne(process.argv[3])
else main()
