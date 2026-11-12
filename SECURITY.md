# Security policy

## Supported versions

Security fixes go into `main` and ship in the next release of
[`pyfect-dev`](https://pypi.org/project/pyfect-dev/) on PyPI. Only the latest release is
supported: update to it to get a fix. Until 1.0, a fix is not backported to earlier minor
versions.

| Version                 | Supported |
| ----------------------- | --------- |
| latest release, `main`  | Yes       |
| older releases          | No        |

## Reporting a vulnerability

Do not open a public issue, pull request or discussion for a vulnerability.

Report it privately through GitHub's private vulnerability reporting: open
<https://github.com/tylergibbs1/pyfect/security/advisories/new> (Security tab, then
"Report a vulnerability"). Only the maintainer sees the report.

Include:

1. the affected module, and the release or commit;
2. what an attacker controls and what they gain;
3. a minimal reproduction, ideally a failing pytest test.

The maintainer aims to acknowledge a report within 7 days and to say within 30 days whether
and how it will be fixed. Fixes are developed in a private fork of the advisory, released,
and then the advisory is published with a CVE where one applies, crediting you unless you ask
not to be named. Please keep the details private until the advisory is published, or for 90
days after your report if that comes first.

## Scope

pyfect follows Effect v4's APIs, but where Effect's default is unsafe pyfect picks the safe
one (body size limits, same-origin WebSocket and RPC upgrades, strict request parsing,
bounded decompression and more). Each such divergence is listed in the decisions table of
[docs/PARITY.md](docs/PARITY.md), and the guides on HTTP servers, RPC and MCP list the
defaults under "Security defaults". A way around one of these defaults is a vulnerability.

In scope: code in `src/pyfect` reached with input from outside the process (HTTP requests and
responses, WebSocket and RPC messages, tokens, keys and ciphertexts, archives, encoded text
and binary data, configuration files), the handling of secrets (`Redacted`, keys), and the
release pipeline (`.github/workflows`).

Out of scope: input the application itself trusts by design, such as a `pyfect.workers`
child process (its messages are pickles, so the parent and child must be the same program),
SQL passed to `sql.unsafe`, or a shell command line the application builds; and
vulnerabilities in dependencies, which belong to their projects (the `audit` workflow checks
the locked dependencies weekly).

## Past reviews

- [Security review, November 2026](docs/security-review-2026-11.md): a manual audit of the
  code that handles untrusted input or secrets, after fuzzing every parser (`tests/fuzz`).
