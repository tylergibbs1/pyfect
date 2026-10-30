# Security policy

## Supported versions

Only `main` gets security fixes. Releases are cut from `main`, so update to the latest
commit or release to get a fix.

| Version | Supported |
| ------- | --------- |
| `main`  | Yes       |
| older   | No        |

## Reporting a vulnerability

Do not open a public issue, pull request or discussion for a vulnerability.

Report it privately through GitHub's security advisories:

1. Open <https://github.com/tylergibbs1/pyfect/security/advisories/new>
   (Security tab, then "Report a vulnerability").
2. Describe the affected module and commit, what an attacker controls, and the impact.
3. Include a minimal reproduction, ideally a failing pytest test.

The maintainer will acknowledge the report, work on a fix in a private fork of the advisory,
and credit you in the published advisory unless you ask not to be named. Please keep the
details private until the advisory is published.

## Scope

pyfect follows Effect v4's APIs, but where Effect's default is unsafe pyfect picks the safe
one (body size limits, same-origin WebSocket and RPC upgrades, strict request parsing,
bounded decompression and more). Each such divergence is listed in the decisions table of
[docs/PARITY.md](docs/PARITY.md), and the guides on HTTP servers, RPC and MCP list the
defaults under "Security defaults". A way around one of these defaults is a vulnerability.
