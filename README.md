<p align="center">
  <img src="assets/logo.svg" width="72" height="72" alt="pyfect logo">
</p>

<h1 align="center">pyfect</h1>

<p align="center">
  <a href="https://effect.website">Effect</a> for Python. Errors, dependencies and concurrency checked by pyright.
</p>

<p align="center">
  <a href="https://pyfect.dev/docs"><img alt="Docs" src="https://img.shields.io/badge/docs-pyfect.dev-0a0a0a"></a>
  <img alt="Python 3.13+" src="https://img.shields.io/badge/python-3.13%2B-0a0a0a">
  <img alt="pyright strict" src="https://img.shields.io/badge/pyright-strict-0a0a0a">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-0a0a0a"></a>
</p>

<p align="center">
  <a href="https://pyfect.dev/docs"><b>Read the docs</b></a> ·
  <a href="https://pyfect.dev/docs/installation">Install</a> ·
  <a href="examples/">Examples</a> ·
  <a href="docs/PARITY.md">Parity with Effect</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

---

pyfect lets you write Python programs whose type says what they return, how they can fail
and which services they need, so pyright rejects a program that forgets to handle an error
or provide a dependency. It is for Python developers building services, pipelines and CLIs
who want Effect's model (typed errors, structured concurrency, layers, streams, schema)
without leaving Python.

## A quick look

```python
from dataclasses import dataclass
from typing import Protocol

import pyfect as fx
from pyfect import layer


class UserStore(Protocol):
    def find(self, user_id: str) -> fx.Effect[str | None]: ...


class Users(fx.Tag[UserStore]): ...


class InMemoryUsers:
    def find(self, user_id: str) -> fx.Effect[str | None]:
        return fx.succeed({"1": "Ada"}.get(user_id))


@dataclass
class UserNotFound(fx.TaggedError):
    user_id: str


@fx.fn
def greet(user_id: str):
    users = yield from Users()
    name = yield from users.find(user_id)
    if name is None:
        return (yield from UserNotFound(user_id))
    return f"Hello, {name}!"


# greet("1") is inferred as Effect[str, UserNotFound, Users]

program = (
    greet("1")
    .pipe(fx.catch_tag(UserNotFound, lambda e: fx.succeed("Who?")))
    .pipe(fx.provide(layer.succeed(Users, InMemoryUsers())))
)

fx.run_blocking(program)
```

Remove the `catch_tag` line and pyright stops you before the program runs:

```text
error: Argument of type "Effect[str, UserNotFound, Never]" cannot be assigned to
       parameter "eff" of type "Effect[A@run_blocking, Never, Never]"
    Type "UserNotFound" is not assignable to type "Never"
```

[`examples/quickstart.py`](examples/quickstart.py) builds on this with a resource-managed
layer, concurrency, retries and timeouts.

## How it works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/how-it-works-dark.svg">
    <img src="assets/how-it-works-light.svg" alt="An @fx.fn generator builds Effect[A, E, R]; catch_tag removes an error, provide(layer) removes a service, and run_blocking runs the Effect[A, Never, Never] to an Exit." width="225">
  </picture>
</p>

1. **Describe.** A generator decorated with `@fx.fn` builds an `Effect[A, E, R]`: a value
   that describes the work. Nothing runs yet, and pyright infers all three types with no
   annotations.
2. **Narrow.** Each handler removes exactly the error it handles, and each layer removes
   exactly the services it builds. The type shrinks as you go.
3. **Run.** Only an effect with no errors and no services left can run. pyfect runs it on
   its own fiber scheduler, synchronously or on asyncio, with structured concurrency and
   interruption that always runs finalizers.

## Features

- **Typed errors.** Expected failures live in the type; `catch_tag` handles one, and
  defects stay separate. [Errors →](https://pyfect.dev/docs/errors)
- **Services and layers.** Dependency injection checked by the type checker, with memoized,
  concurrently built layers that release their resources in order.
  [Services →](https://pyfect.dev/docs/services)
- **A fiber runtime of its own.** The same program runs with `run_blocking` (no event loop) or on
  asyncio. `blocking` moves blocking calls to a thread. [Effects →](https://pyfect.dev/docs/effects)
- **Structured concurrency.** Children end with their parent; `all` and `for_each` take a
  concurrency limit; races wait for losers to clean up.
  [Concurrency →](https://pyfect.dev/docs/concurrency)
- **Resources.** Scopes, `acquire_release`, pools, `RcRef` and `RcMap` release exactly once,
  even on interruption. [Resources →](https://pyfect.dev/docs/resources)
- **Retries and schedules.** Exponential, jittered, cron and composed schedules for `retry`
  and `repeat`. [Schedules →](https://pyfect.dev/docs/schedules)
- **Streams.** Pull-based streams, sinks and channels with backpressure, plus NDJSON, JSON
  array and Server-Sent Events framers. [Streams →](https://pyfect.dev/docs/streams)
- **Schema.** Decode and encode data with Effect's error messages, generate JSON Schema and
  Hypothesis strategies, store schemas themselves as JSON documents, and plug into pydantic
  or msgspec.
  [Schema →](https://pyfect.dev/docs/schema)
- **Transactions.** Software transactional memory: `TxRef`, transactional queues, maps,
  locks and semaphores that commit atomically and retry without blocking a thread.
  [Transactions →](https://pyfect.dev/docs/transactions)
- **Graphs.** Directed and undirected graphs with stable indexes: walks, shortest paths,
  components, flows and matchings, GraphViz and Mermaid output, and a schema for storing
  them as JSON. [Graphs →](https://pyfect.dev/docs/graph)
- **Config.** Typed settings from the environment, `.env` files or dicts, with secrets kept
  out of logs. [Config →](https://pyfect.dev/docs/config)
- **Observability.** Logging, spans, metrics and an OpenTelemetry bridge.
  [Observability →](https://pyfect.dev/docs/observability)
- **Platform.** Files, child processes, an HTTP client (httpx), an HTTP server (standard library,
  uvicorn, hypercorn for HTTP/2, or any ASGI server), and TCP, TLS, WebSocket
  and UDP sockets, all as services you can swap in tests. [Platform →](https://pyfect.dev/docs/platform)
- **SQL.** Statements built from literal templates, so values are always bound parameters;
  transactions with savepoints, batching resolvers and migrations, on SQLite (standard
  library), PostgreSQL (psycopg), MySQL (asyncmy), SQL Server (python-tds), libSQL and
  Turso, ClickHouse and Cloudflare D1 (the last three over HTTP). [SQL →](https://pyfect.dev/docs/sql)
- **CLI.** Typed commands, flags and arguments with subcommands, generated help, shell
  completions and interactive prompts. [CLI →](https://pyfect.dev/docs/cli)
- **HTTP server.** Routes and middleware added by layers, each handler an effect, served on
  uvicorn or as an ASGI app. [HTTP server →](https://pyfect.dev/docs/http-server)
- **HttpApi.** Declare an API once with schemas, then serve it, call it with a derived client
  and document it with OpenAPI and Swagger UI. [HttpApi →](https://pyfect.dev/docs/http-api)
- **RPC.** Typed procedures over HTTP, WebSockets or workers (threads and child processes),
  with streamed results and an in-memory test client. [RPC →](https://pyfect.dev/docs/rpc)
- **Persistence.** Key-value stores, caches whose results outlive the process and durable
  at-least-once queues, in memory, files, SQL or Redis.
  [Persistence →](https://pyfect.dev/docs/persistence)
- **Rate limiting and circuit breakers.** Limits and breakers per key, in memory or shared
  by every process through Redis, and HTTP clients that follow a server's rate limit
  headers. [Rate limiting →](https://pyfect.dev/docs/rate-limiting)
- **Workers.** Run code on threads or in child processes and talk to it by messages or
  typed RPC calls over a pool. [Workers →](https://pyfect.dev/docs/workers)
- **Workflows.** Durable workflows whose steps run once and are replayed, with durable
  sleeps, waits completed from outside and compensation on failure.
  [Workflows →](https://pyfect.dev/docs/workflows)
- **AI.** A provider-neutral `LanguageModel` for text, structured output, streaming and
  typed tools, chats that keep their history, typed decisions (classify, rate,
  probability), and Anthropic, OpenAI, OpenAI-compatible, OpenRouter, Cloudflare and
  TypeSafe providers over the HTTP client. [AI →](https://pyfect.dev/docs/ai)
- **MCP.** Serve a toolkit over the Model Context Protocol on HTTP or stdio, and call any
  MCP server's tools. [MCP →](https://pyfect.dev/docs/mcp)
- **Models.** One class for a table's row and its insert, update and JSON variants, with
  typed repositories on any SQL client. [Models →](https://pyfect.dev/docs/models)
- **GraphQL.** Typed queries, mutations and subscriptions over HTTP, Server-Sent Events or
  WebSockets, with middleware, pagination and batched lookups.
  [GraphQL →](https://pyfect.dev/docs/graphql)
- **Event log.** Events written to a local journal, replayed through handlers and synced
  with a server, encrypted end to end if you like. [Event log →](https://pyfect.dev/docs/eventlog)
- **Cluster.** Stateful entities sharded over runners that talk over TCP, HTTP or
  WebSockets, with messages and shard locks in SQL, singletons and cron jobs that run once
  across the cluster, and durable workflows that resume on another runner when one stops.
  [Cluster →](https://pyfect.dev/docs/cluster)
- **Atoms.** Reactive values in a registry: derived atoms that update when what they read
  changes, effect, stream and RPC or HTTP API atoms, and state handed from a server to a
  client by hydration. [Atoms →](https://pyfect.dev/docs/atoms)
- **Deterministic tests.** A pytest plugin with a virtual clock, so a test of a 30-second
  retry takes no real time. [Testing →](https://pyfect.dev/docs/testing)

pyfect follows Effect v4, does what Effect does wherever Python can express it, and runs
Effect's own test cases as its spec: over 21,000 tests, with a test that fails on any Effect
test title neither ported nor omitted with a reason, and about 94% of Effect's API so far. Every
export of the core modules is listed against Effect's in [`docs/coverage/`](docs/coverage), and
[`docs/PARITY.md`](docs/PARITY.md) tracks what is done, what is open and what still differs. A
bare number as a `Duration` is milliseconds, as in Effect, since 0.2.0 (0.1.0 read it as seconds);
write `"5 seconds"` or a `timedelta` to say the unit.

## Installation

pyfect needs Python 3.13 or later; its one dependency is `typing-extensions`. It is not on PyPI
yet: install the `pyfect-dev` distribution from GitHub and `import pyfect` (PyPI's `pyfect` is
an unrelated project).

```sh
uv add "pyfect-dev @ git+https://github.com/tylergibbs1/pyfect"
```

Optional extras: `otel` (OpenTelemetry), `hypothesis`, `pydantic`, `msgspec`, `httpx` (the
HTTP client backend), `websockets` (WebSocket clients and servers), `server` (the uvicorn
HTTP server), `pg` (the PostgreSQL driver, on psycopg), `mysql` (the MySQL driver, on
asyncmy), `mssql` (the SQL Server driver, on python-tds), `redis` (the Redis client, on
redis-py), `eventlog` (the event log's encryption, on cryptography), `brotli` (`br` response
compression on a live server), `http2` (the HTTP/2 server, on hypercorn), `intl` (`Intl`-style
date formatting, on babel) and `regex` (more ECMAScript patterns in schemas), for example
`uv add "pyfect-dev[otel] @ git+https://github.com/tylergibbs1/pyfect"`.

pyright is the type checker pyfect is designed for. In strict mode, add
`reportUnknownParameterType = false`: pyright reads an unannotated generator's send type as
`Unknown` ([pyright#10279](https://github.com/microsoft/pyright/issues/10279)), and effect
generators never use it. See [Installation](https://pyfect.dev/docs/installation).

## Learn more

- [Documentation](https://pyfect.dev/docs): guides for each part of the library.
- [API reference](https://pyfect.dev/docs/reference): every public function and class.
- [Examples](examples/): a quickstart, batching, a FastAPI-style service, a stream pipeline
  and schema decoding, all checked by pyright.
- [Effect's docs](https://effect.website/docs): the concepts carry over; pyfect uses
  snake_case and `yield from` in place of `yield*`.

## Contributing

Contributions are welcome. [`CONTRIBUTING.md`](CONTRIBUTING.md) covers setup, the one
command that checks everything, and how a change is ported from Effect. Issues labelled
[good first issue](https://github.com/tylergibbs1/pyfect/labels/good%20first%20issue) are a
good place to start. Everyone taking part agrees to the
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE). pyfect is an independent port and is not affiliated with Effectful
Technologies; Effect is MIT-licensed by its authors.
