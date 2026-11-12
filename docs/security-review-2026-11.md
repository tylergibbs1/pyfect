# Security review, November 2026

A manual audit of the code in pyfect 0.6.1 that handles untrusted input or secrets, done
after fuzzing every parser of untrusted input (`tests/fuzz`, see the 0.6.1 changelog). It
covers exit criterion 5, "Untrusted input is fuzzed and reviewed".

- **Reviewed:** release 0.6.1 (`f856cf92`), compared with Effect 4.1.2 (`506eef14`).
- **Method:** source reading of each area against the attack classes listed below, with
  small local probes (dummy keys, loopback servers, mock transports) to confirm behaviour.
  Each finding names what an attacker controls, what they gain, and what Effect does in the
  same situation.
- **Not covered:** deployment (proxies, TLS termination, hosting), dependencies' own code
  beyond how pyfect calls them, Windows behaviour (read from source only), and the HTTP/2
  paths inside hypercorn.

Severity follows the usual scale: critical (unauthenticated code execution or full data
access), high (an explicit control fully defeated), medium (a real boundary crossed with a
limited blast radius), low (minor disclosure, or a denial of service that needs sustained
effort), informational (hardening).

## Summary

No critical or high-severity issue was found. The parsers already refuse the classic
attacks (request smuggling, algorithm confusion, decompression bombs, path traversal), and in
several places pyfect is stricter than Effect by design (see the decisions table in
[PARITY.md](PARITY.md)).

| #   | Severity | Area                     | Finding                                                      | Status                    |
| --- | -------- | ------------------------ | ------------------------------------------------------------ | ------------------------- |
| F1  | Medium   | HTTP client              | httpx's cookie jar shared cookies between callers            | Fixed                     |
| F2  | Low      | JOSE / schema            | A JWT time claim past the largest double never expired       | Fixed                     |
| F3  | Low      | HTTP server              | A head sent a byte at a time cost quadratic CPU               | Fixed                     |
| F4  | Low      | Workers                  | A grandchild could read pickles from an inherited fd number   | Fixed                     |
| F5  | Info     | Schema compiler          | A literal's `repr` was pasted into generated code            | Fixed                     |
| F6  | Info     | Supply chain             | No dependency audit, no guard on workflow pinning            | Fixed (workflow, test)    |
| W1  | Medium   | (withheld)               | Withheld until the owner decides on it                       | Owner decision            |
| W2  | Medium   | (withheld)               | Withheld until the owner decides on it                       | Owner decision            |
| D1  | Low      | SQL (ClickHouse)         | A backslash in a quoted identifier is not escaped            | Owner decision (as Effect) |
| D2  | Low      | SQL (MySQL)              | TLS does not check the hostname unless `verify_identity`     | Owner decision (as Effect) |
| D3  | Low      | Release                  | The `pypi` environment and version tags are unprotected      | Owner decision (settings) |
| H1–H12 | Info  | various                  | Hardening notes, mostly shared with Effect                   | Documented                |

## Fixed

### F1. The httpx client kept cookies across requests (medium)

- **Where:** `src/pyfect/http/httpx_client.py`, `_Backend`.
- **What happened:** `httpx.AsyncClient` was built with httpx's default cookie jar, which
  stores every `Set-Cookie` and adds matching cookies to every later request on that client.
  pyfect already took the `cookies=` option out of httpx's hands and documents
  `with_cookies_ref` as the way to keep cookies, but httpx's own jar stayed on.
- **Exploit scenario:** a server shares one `HttpClient` layer between its users and calls an
  upstream service on each user's behalf. The upstream sets a session cookie in its answer
  to user A; user B's next call to that host carries A's session. Cookies stayed scoped to
  their domain, so nothing went to another host.
- **Effect:** `FetchHttpClient` calls `fetch`, which has no cookie jar in Node, so nothing
  persists.
- **Fix:** the client gets a jar whose policy refuses every cookie. Test:
  `tests/test_http_client_cookie_jar.py::test_a_client_without_a_jar_keeps_no_cookies`.

### F2. A JWT time claim past the largest double never expired (low)

- **Where:** `src/pyfect/schema/_checks_number.py` (`is_finite`), used by `jose/jwt.py` for
  `exp`, `nbf` and `iat`.
- **What happened:** Python reads a JSON integer exactly, and `S.Finite` treated every `int`
  as finite. A token whose `exp` was a 400-digit integer verified as never expiring; a
  hugely negative `nbf` was valid at once.
- **Exploit scenario:** needs a token the issuer signed, so an attacker cannot forge one;
  an issuer that mints such a value by mistake hands out a token that never expires in pyfect
  and is refused in Effect.
- **Effect:** `JSON.parse` reads the literal as `Infinity` and `Schema.Finite` rejects it,
  giving `ClaimValidationFailed("exp", "invalid")` (`jose/Jwt.ts`).
- **Fix:** `is_finite` reads an `int` as a JavaScript number: one that rounds to infinity as
  a double is not finite. This covers every schema decoding JSON numbers, not only JOSE.
  Tests: `tests/test_jose_claim_numbers.py`,
  `tests/test_schema_checks.py::test_finite_reads_an_int_as_a_javascript_number`.

### F3. A request head sent a byte at a time cost quadratic CPU (low)

- **Where:** `src/pyfect/http/live_server/_inbound.py`, `read_head` and `read_line`.
- **What happened:** every arrival searched the whole buffered head again for its end and for
  a bare LF. A 16 KiB head (the limit) sent one byte per packet cost about a second of CPU on
  the server's single event loop, against about a millisecond sent whole.
- **Exploit scenario:** an unauthenticated client opens a few connections and drips heads,
  slowing every other request on the server. The headers timeout (60 s) bounds each
  connection, so the effect is a slowdown proportional to the attacker's connections.
- **Effect / Node:** llhttp parses incrementally, so each byte is examined once.
- **Fix:** each read remembers how far it has searched and resumes there (three bytes back
  for the four-byte head end). Test: `tests/test_live_server_slow_head.py` (a 32 KiB dripped
  head must take under eight times as long as an 8 KiB one; it took fifteen times before).

### F4. A worker's grandchild could take the worker channel (low)

- **Where:** `src/pyfect/workers/_process.py`, `current_parent`.
- **What happened:** the channel to a worker process is a `socketpair` passed only to that
  child, so no other process can write to it. Its descriptor number travels in
  `PYFECT_WORKER_FD`, which the worker removes from its environment only when it first looks
  for its parent. A worker that started a process before that passed the variable on, and if
  that process was itself a pyfect worker program it would unpickle whatever its own
  descriptor of that number was (possibly a network socket).
- **Exploit scenario:** contrived: it needs a worker that starts another pyfect worker
  program before reading its channel, and a descriptor-number collision with a socket an
  attacker writes to. The result would be code execution through `pickle`.
- **Effect:** Effect's workers use Node's IPC channel or `worker_threads`, which carry no
  inheritable descriptor number.
- **Fix:** the parent also passes its pid (`PYFECT_WORKER_PARENT`), and a process whose
  parent is another ignores the channel. Test: `tests/test_worker_channel_inheritance.py`.

### F5. Generated decoders pasted a literal's `repr` into source (informational)

- **Where:** `src/pyfect/schema/compiler/_codegen.py`, `_literal_source`.
- **What happened:** a literal that was an instance of `bool`, `int` or `str` was written into
  the generated source as its `repr`, including subclasses whose `repr` is their own code. A
  `str` subclass with a custom `__repr__` had that text run by the JIT; an `IntEnum` literal
  gave source that did not compile (the schema then fell back to interpreting).
- **Reachability:** none from decoded input: field names and literals parsed from JSON are
  plain `str`, and other values go in as bound constants. Exploiting it needs attacker
  objects inside the schema definition, which is already code execution.
- **Fix:** only the exact builtin types are written as source; anything else is a bound
  constant. Test: `tests/test_schema_codegen_literals.py`.

### F6. Supply chain (informational)

The workflows were already in good shape: every action pinned to a commit SHA, top-level
`permissions: contents: read`, no `pull_request_target`, no pull-request text interpolated
into scripts, `uv sync --locked` and `bun install --frozen-lockfile`, and trusted publishing
with the build and publish in separate jobs and PEP 740 attestations. What was missing:

- a check of the locked dependencies against known vulnerabilities: `uv audit` and
  `bun audit` find none today (68 Python and 431 website packages). The new
  `.github/workflows/audit.yml` runs both on every push and pull request and weekly;
- a guard that keeps the workflow rules: `tests/test_workflow_security.py` fails on an
  unpinned action, `pull_request_target`, a workflow without read-only top-level
  permissions, an `id-token: write` outside the publish job, or `github.event.*` /
  `github.head_ref` text in a workflow.

`SECURITY.md` now states the supported release, response times and scope, and has a
placeholder for a security contact address.

## Owner decisions

### W1, W2. Withheld

Two medium findings are not described in this public document until the owner decides how
to fix them; each fix changes behaviour a working program could rely on. They are described
in the review hand-off to the owner, and this section will describe them once fixed.

### D1. ClickHouse quoted identifiers keep backslashes (low, as Effect)

`sql/clickhouse/client.py` quotes identifiers with `"` doubled but leaves `\` alone;
ClickHouse reads a backslash in a quoted identifier as an escape, so an identifier ending in
`\` ends the quoting early. Identifiers are normally written by the developer; an app that
builds them from user input (a column picker, for example) could be injected. Effect's
`ClickhouseClient.ts` escapes the same way. Proposed fix: also double `\`, a divergence from
Effect.

### D2. MySQL TLS does not check the hostname by default (low, as Effect)

`sql/mysql/_url_options.py` defaults `verify_identity` to `False`, as mysql2 (Effect's
driver) does: any certificate from a trusted CA is accepted for any host, so a
man-in-the-middle holding such a certificate can read the connection. Proposed fix: default
`verify_identity=True` when TLS is on, a Changed entry and a divergence from Effect.

### D3. The `pypi` environment and version tags are unprotected (low)

Read from the repository settings (not changed): the `pypi` environment has no protection
rules and no deployment branch or tag policy, and no ruleset protects `v*` tags. Anyone with
write access can publish any commit that passes CI by pushing a tag, from any branch. With a
single maintainer this is the maintainer's own authority, but a leaked token with `contents:
write` could publish. Proposed: a deployment tag policy of `v*` on the `pypi` environment
with the maintainer as required reviewer, and a ruleset that restricts creating `v*` tags.

## Hardening notes

Each is documented rather than changed; unless stated, Effect behaves the same.

- **H1. Client response size.** No default cap on response bodies, and decompression of
  responses is unbounded (`with_body_limit` exists, counts decoded bytes, and is opt-in).
  Apps that fetch user-supplied URLs should set it.
- **H2. Client environment.** httpx's `trust_env=True` reads `HTTP(S)_PROXY`,
  `SSL_CERT_FILE` and `~/.netrc`; Node's fetch ignores the proxy variables. The environment
  is operator-controlled, so this is a parity note rather than a boundary.
- **H3. No SSRF policy.** The client follows the URL it is given (redirects included) to
  any address, private ones too. Apps fetching user-supplied URLs need their own allowlist,
  checked after DNS resolution.
- **H4. Origin check.** The default same-origin check of WebSocket upgrades and RPC calls
  compares host and port, not scheme, and trusts `Host`, so a DNS-rebinding page passes it
  (without the victim's cookies for the real host). Effect and `ws` check no origin at all.
- **H5. uvicorn engine.** `uvicorn_server` keeps uvicorn's `proxy_headers=True`, trusting
  `X-Forwarded-For` / `-Proto` from 127.0.0.1, where the live server trusts nothing unless
  `x_forwarded_headers` is configured. Worth documenting or setting explicitly.
- **H6. Routing.** Routes match case-insensitively with slashes and `%xx` normalised, as
  find-my-way does. Global middleware that guards by `request.url.startswith("/admin")` can
  be passed with `/ADMIN`; put guards on routes.
- **H7. Static files.** The static server follows symlinks out of its root and serves
  dotfiles; Windows device names are not filtered. Only the path text is confined.
- **H8. WebSocket.** No idle timeout, and a 100 MiB default message limit (as `ws`); many
  slow connections can hold a lot of memory.
- **H9. Content-Length.** Identical duplicate `Content-Length` values are merged (RFC 9112
  allows it; llhttp refuses any duplicate), and up to 1000 digits are read. Neither changes
  framing: differing values are a 400 and an oversized body a 413.
- **H10. JOSE.** ECDSA high-S signatures verify (as WebCrypto), so a token string is
  malleable: don't deduplicate tokens by their text. An RSA JWK without `alg` verifies both
  RS* and PS*. `typ` is checked only when asked for. A secret JWK's string `key_ops` is
  matched as a substring. `dir` + A256GCM uses random 96-bit nonces, so one key should
  encrypt fewer than 2^32 tokens. `import_pkcs8` also reads PKCS#1 RSA keys (OpenSSL's
  loader).
- **H11. Secrets in logs.** A pickled `Redacted` holds its value (needed for workers; crypto
  keys refuse pickling). OTLP exporter headers outside the default redaction list (such as
  vendor API key headers) appear in debug logs of a failed export.
- **H12. Listening sockets.** Servers bind every interface when no host is given (as Node);
  pass `host="127.0.0.1"` for local-only tools such as devtools.

## Checked and found sound

### Crypto and JOSE (`src/pyfect/crypto`, `src/pyfect/jose`)

- `alg: none` is refused (not in the algorithm schema). HS/RS confusion is impossible: keys
  are typed, a token's `alg` must equal the key's, and `verify_with_key_set` takes an
  allowlist of asymmetric algorithms and re-checks the resolved key. Key family and curve are
  checked against the algorithm on import.
- Header-embedded keys (`jwk`, `jku`, `x5u`, `x5c`) are never used; only `kid` reaches the
  resolver. JWKS candidates filter on `kty`, `crv`, `kid`, `alg`, `use` and `key_ops`, and an
  ambiguous match fails.
- `crit` and `b64` are refused in JWS, `crit` and `zip` in JWE (so no compression before
  encryption and no decompression on decrypt). JWE supports only `dir` + `A256GCM`, as in
  Effect, so RSA1_5 (Bleichenbacher), PBES2 (`p2c`), ECDH-ES (`epk`) and CBC-HMAC attacks do
  not apply.
- JWT claims (`exp`, `nbf`, `iat`, `iss`, `sub`, `aud`, `typ`, required claims, clock
  tolerance, maximum age) follow `Jwt.ts`; `iss` and `aud` need exact membership.
- MACs are compared with `hmac.compare_digest`; no `==` on secret bytes.
- ES* signatures must be raw `r‖s` of the exact length (DER refused); Ed25519 signatures are
  64 bytes, RSA signatures the modulus length. RSA-PSS uses the hash length as salt.
- RSA keys under 2048 bits, HMAC keys under the hash size, off-curve EC points, inconsistent
  private JWKs and non-canonical base64url are refused. X25519's all-zero shared secret is
  refused.
- AEAD nonce lengths are exact, GCM tags 128 bits only; every authentication, padding,
  RSA-OAEP and AES-KW failure is the same error (no oracle).
- KDF parameters (HKDF length, PBKDF2 iterations, Argon2id per RFC 9106) are bounded and never
  read from a token. Randomness is `os.urandom`, with rejection sampling for ranges.
- No deprecated or unsafe `cryptography` API; key loading goes through one module
  (`crypto/_lib.py`, guarded by `tests/test_crypto_key_loading_guard.py`). Errors never
  include key material; keys refuse pickling; tokens and private JWKs are `Redacted`.
- Remote JWKS: HTTPS only, no credentials in the URL, redirects refused, 128 KiB and 64 keys
  at most, a timeout, refetches rate-limited, private members refused.

### HTTP server (`src/pyfect/http/live_server`, ASGI engines, middleware)

- Request smuggling: `Content-Length` with `Transfer-Encoding`, any coding other than a
  final `chunked`, `TE` on HTTP/1.0, signed or hex `Content-Length`, differing duplicates,
  obs-fold, whitespace before a colon, NUL, bare CR or LF, duplicate or missing `Host`, and
  malformed chunk sizes, extensions and trailers are all refused, matching llhttp. An
  upgrade the app does not take closes the connection, so the bytes after it are never read
  as a request.
- Limits: 16 KiB heads (431), `MaxBodySize` of 10 MiB on whole-body reads, applied to
  chunked and decompressed bodies; at most two stacked content codings, inflated in 64 KiB
  pieces against the limit; Node's timeouts (headers 60 s, keep-alive 5 s, request 300 s).
- Multipart: RFC 2046 boundaries, part headers bounded, fields 10 MiB, uploads in a `mkdtemp`
  (0700) directory removed with the scope, file names reduced to a safe basename.
- WebSocket: handshake checks match `ws`; client frames must be masked; control frames at most
  125 bytes; size checked before buffering; permessage-deflate inflation bounded and off by
  default; same-origin check on by default.
- Responses: header names, values and status text with control characters are never sent;
  cookie attributes are validated and values encoded; error responses have empty bodies.
- Static files: paths decoded once, NUL refused, `..`, `%2e%2e` and `\` cannot leave the
  root; one byte range at most; the directory redirect cannot become an open redirect.
- `x_forwarded_headers` is opt-in, needs trusted proxies, and validates the forwarded host.
  CORS refuses `credentials=True` with `*` (Effect sends it) and matches origins exactly.
- TLS: `PROTOCOL_TLS_SERVER` with Python's defaults (TLS 1.2 or later).

### HTTP client

- Redirects drop `authorization`, `proxy-authorization`, `cookie` and every redacted header
  name on a hop to another origin (Effect drops the first two only), refuse `https` to
  `http` (Effect follows it), stop after 10 hops, and turn 303 (and 301/302 after POST) into
  a bodiless GET. httpx's own redirect following is off, and client-level headers, cookies,
  params and auth are applied before the redirect logic so they are stripped too.
- Certificates and hostnames are verified by default. CR or LF in an outgoing header value
  is refused on the wire. Headers, URLs (user info, redacted parameters) and spans are
  redacted in logs and traces.

### Deserialization, encodings and the rest

- No `eval`, `marshal`, `yaml.load` or `shell=True` in `src`; `pickle.loads` only in
  `workers/_frames.py`, over a `socketpair` to the process's own child (see F4).
  `importlib` takes only fixed or generated module names. Redis `eval` runs constant Lua
  scripts.
- RPC: no MessagePack; JSON and NDJSON framing have buffer limits; `schema_binary` bounds
  frame sizes, item counts, nesting and varints; transport headers win over message headers.
- Event log: AES-GCM with a fresh random nonce per batch, AAD binding store and entry ids;
  session challenges are single-use and expire.
- Archives: tar and zip decode to streams only and never write to disk (the docs warn that
  entry names may be absolute, contain `..` or be links); zip entries are checked against
  their headers and buffered at most 4 MiB compressed.
- SQL: values are always parameters; identifiers are quoted per dialect (see D1);
  `sql.literal` takes only a `LiteralString`.
- Processes: arguments go to `Popen` as a list; the `shell` option refuses interpolated
  values.
- Config: dotenv `${}` expansion is opt-in and reads only the same file, never the process
  environment.
- Temporary files: `mkdtemp` (0700) directories, a temporary file inside its own directory,
  cleanup with `shutil.rmtree` (which does not follow symlinks).
- File key-value store: keys are percent-encoded as `encodeURIComponent`, so no traversal.
- AI clients: API keys are `Redacted` and sent in headers on the redaction list.

## Attack classes considered

Algorithm confusion, embedded keys, critical headers, signature malleability, timing and
padding oracles, nonce reuse, weak keys, KDF parameter abuse; request smuggling, header and
body limits, decompression bombs, slow clients, multipart abuse, cross-site WebSocket
hijacking, CORS misconfiguration, forwarded-header trust, path traversal, header and cookie
injection, error disclosure; credential leaks across redirects, scheme downgrade, TLS
verification, SSRF; unsafe deserialization and code generation, archive traversal and bombs,
SQL and shell injection, secrets in logs, temporary file races; workflow injection,
unpinned actions, token permissions, release integrity and known-vulnerable dependencies.
