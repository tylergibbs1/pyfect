<p align="center">
  <img src="https://raw.githubusercontent.com/tylergibbs1/pyfect/main/assets/logo.svg" width="72" height="72" alt="pyfect logo">
</p>

<h1 align="center">pyfect</h1>

<p align="center">
  <a href="https://effect.website">Effect</a> for Python. Errors, dependencies and concurrency checked by pyright.
</p>

<p align="center">
  <a href="https://pypi.org/project/pyfect-dev/"><img alt="PyPI" src="https://img.shields.io/pypi/v/pyfect-dev?color=0a0a0a&label=pypi"></a>
  <a href="https://pyfect.dev/docs"><img alt="Docs" src="https://img.shields.io/badge/docs-pyfect.dev-0a0a0a"></a>
  <img alt="Python 3.13+" src="https://img.shields.io/badge/python-3.13%2B-0a0a0a">
  <img alt="pyright strict" src="https://img.shields.io/badge/pyright-strict-0a0a0a">
  <a href="https://github.com/tylergibbs1/pyfect/blob/main/LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-0a0a0a"></a>
</p>

<p align="center">
  <a href="https://pyfect.dev/docs"><b>Read the docs</b></a> ·
  <a href="https://pyfect.dev/docs/installation">Install</a> ·
  <a href="https://github.com/tylergibbs1/pyfect/tree/main/examples">Examples</a> ·
  <a href="https://github.com/tylergibbs1/pyfect/blob/main/docs/PARITY.md">Parity with Effect</a> ·
  <a href="https://github.com/tylergibbs1/pyfect/blob/main/CONTRIBUTING.md">Contribute</a>
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

print(fx.run_blocking(program))  # Hello, Ada!
```

Remove the `catch_tag` line and pyright stops you before the program runs:

```text
error: Argument of type "Effect[str, UserNotFound, Never]" cannot be assigned to
       parameter "eff" of type "Effect[A@run_blocking, Never, Never]"
    Type "UserNotFound" is not assignable to type "Never"
```

That covers the errors an effect fails with, as `greet` does with `yield from UserNotFound(...)`.
An exception you `raise` is a defect, which the type doesn't track
([Errors](https://pyfect.dev/docs/errors)).

[`examples/quickstart.py`](https://github.com/tylergibbs1/pyfect/blob/main/examples/quickstart.py) builds on this with a resource-managed
layer, concurrency, retries and timeouts.

## How it works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tylergibbs1/pyfect/main/assets/how-it-works-dark.svg">
    <img src="https://raw.githubusercontent.com/tylergibbs1/pyfect/main/assets/how-it-works-light.svg" alt="An @fx.fn generator builds Effect[A, E, R]; catch_tag removes an error, provide(layer) removes a service, and run_blocking runs the Effect[A, Never, Never] to an Exit." width="225">
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

### Core runtime

- **Typed errors**: expected failures live in the type, defects stay separate. [Errors →](https://pyfect.dev/docs/errors)
- **Services and layers**: dependency injection pyright checks, with memoized layers that release in order. [Services →](https://pyfect.dev/docs/services)
- **Its own fiber runtime**: `run_blocking` with no event loop, or on asyncio; `blocking` moves calls to a thread. [Effects →](https://pyfect.dev/docs/effects)
- **Structured concurrency**: children end with their parent, `all` and `for_each` take a limit, races clean up. [Concurrency →](https://pyfect.dev/docs/concurrency)
- **Resources**: scopes, `acquire_release`, pools, `RcRef` and `RcMap` release exactly once, even on interruption. [Resources →](https://pyfect.dev/docs/resources)
- **Retries and schedules**: exponential, jittered, cron and composed schedules for `retry` and `repeat`. [Schedules →](https://pyfect.dev/docs/schedules)
- **Streams**: pull-based streams, sinks and channels with backpressure, plus NDJSON and SSE framers. [Streams →](https://pyfect.dev/docs/streams)
- **Transactions**: software transactional memory with `TxRef`, queues, maps, locks and semaphores. [Transactions →](https://pyfect.dev/docs/transactions)

### Data

- **Schema**: decode and encode with Effect's messages, compiled decoders, JSON Schema, Hypothesis, pydantic and msgspec. [Schema →](https://pyfect.dev/docs/schema)
- **Config**: typed settings from the environment, `.env` files or dicts, with secrets kept out of logs. [Config →](https://pyfect.dev/docs/config)
- **Graphs**: directed and undirected graphs with walks, shortest paths, flows, matchings and Mermaid output. [Graphs →](https://pyfect.dev/docs/graph)
- **Cryptography**: random ids, digests, encryption, signatures and JOSE tokens, as services. [Cryptography →](https://pyfect.dev/docs/crypto)

### Web, APIs and AI

- **Platform**: files, child processes, an httpx HTTP client and TCP, TLS, WebSocket and UDP sockets, all swappable in tests. [Platform →](https://pyfect.dev/docs/platform)
- **HTTP server**: routes and middleware added by layers, served by the standard library, uvicorn, hypercorn (HTTP/2) or any ASGI server. [HTTP server →](https://pyfect.dev/docs/http-server)
- **HttpApi**: declare an API once with schemas; serve it, call it with a derived client, document it with OpenAPI. [HttpApi →](https://pyfect.dev/docs/http-api)
- **RPC**: typed procedures over HTTP, WebSockets, stdio or workers, with streamed results and a test client. [RPC →](https://pyfect.dev/docs/rpc)
- **GraphQL**: typed queries, mutations and subscriptions over HTTP, SSE or WebSockets, with batched lookups. [GraphQL →](https://pyfect.dev/docs/graphql)
- **CLI**: typed commands, flags and arguments with subcommands, help, shell completions and prompts. [CLI →](https://pyfect.dev/docs/cli)
- **Atoms**: reactive values with derived, effect, stream and RPC atoms, and server-to-client hydration. [Atoms →](https://pyfect.dev/docs/atoms)
- **AI**: a provider-neutral `LanguageModel` with structured output, typed tools and chats, on Anthropic, OpenAI, OpenRouter and more. [AI →](https://pyfect.dev/docs/ai)
- **MCP**: serve a toolkit over the Model Context Protocol on HTTP or stdio, and call any MCP server's tools. [MCP →](https://pyfect.dev/docs/mcp)

### Testing and observability

- **Deterministic tests**: a pytest plugin with a virtual clock, so a test of a 30-second retry takes no real time. [Testing →](https://pyfect.dev/docs/testing)
- **Observability**: logging, spans and metrics, exported over OTLP or through the OpenTelemetry SDK. [Observability →](https://pyfect.dev/docs/observability)

<details>
<summary><b>Storage and distributed systems</b>: SQL, models, persistence, rate limiting, workers, workflows, event log, cluster</summary>

- **SQL**: statements from literal templates, so values are always bound parameters; transactions, migrations and seven dialects. [SQL →](https://pyfect.dev/docs/sql)
- **Models**: one class for a row and its insert, update and JSON variants, with typed repositories. [Models →](https://pyfect.dev/docs/models)
- **Persistence**: key-value stores, persisted caches and durable at-least-once queues in memory, files, SQL or Redis. [Persistence →](https://pyfect.dev/docs/persistence)
- **Rate limiting and circuit breakers**: per key, in memory or shared through Redis, and HTTP clients that obey rate limit headers. [Rate limiting →](https://pyfect.dev/docs/rate-limiting)
- **Workers**: run code on threads or in child processes, by messages or typed RPC over a pool. [Workers →](https://pyfect.dev/docs/workers)
- **Workflows**: durable steps whose results are stored and replayed, with durable sleeps, waits completed from outside and compensation. [Workflows →](https://pyfect.dev/docs/workflows)
- **Event log**: events in a local journal, replayed through handlers and synced with a server, optionally end-to-end encrypted. [Event log →](https://pyfect.dev/docs/eventlog)
- **Cluster**: sharded stateful entities, cluster-wide singletons and cron jobs, and workflows that resume on another runner. [Cluster →](https://pyfect.dev/docs/cluster)

</details>

## Parity with Effect

pyfect follows Effect 4.1.2, does what Effect does wherever Python can express it, and runs
Effect's own test cases as its spec: over 37,000 tests, with a test that fails on any Effect
test title neither ported nor omitted with a reason. It covers about 95% of Effect v4 (about 94% of the runtime core) so far. Every
export of the core modules is listed against Effect's in [`docs/coverage/`](https://github.com/tylergibbs1/pyfect/tree/main/docs/coverage), and
[`docs/PARITY.md`](https://github.com/tylergibbs1/pyfect/blob/main/docs/PARITY.md) tracks what is done, what is open and what still differs.

## Installation

pyfect needs Python 3.13 or later. Install the `pyfect-dev` distribution from PyPI and
`import pyfect` (PyPI's `pyfect` is an unrelated project).

```sh
uv init --python 3.14+gil app && cd app   # a new project; skip in one that has a [project] table
uv add pyfect-dev
uv add --dev pyright
```

With pip, in a virtual environment of Python 3.13 or later: `pip install pyfect-dev pyright`.

`3.14+gil` needs uv 0.9.8 or later. [Installation](https://pyfect.dev/docs/installation) covers older uv and Python versions, the optional extras and pyright's settings.

## Learn more

- [Documentation](https://pyfect.dev/docs): guides for each part of the library.
- [API reference](https://pyfect.dev/docs/reference): every public function and class.
- [Changelog](https://github.com/tylergibbs1/pyfect/blob/main/CHANGELOG.md): what each release changed.
- [Examples](https://github.com/tylergibbs1/pyfect/tree/main/examples), all checked by pyright: a quickstart, request batching,
  a CLI, a FastAPI-style service, a typed HTTP API, an MCP server, schema decoding, a stream
  pipeline and a durable workflow.
- [Effect's docs](https://effect.website/docs): the concepts carry over; pyfect uses
  snake_case and `yield from` in place of `yield*`.

## Contributing

Contributions are welcome. [`CONTRIBUTING.md`](https://github.com/tylergibbs1/pyfect/blob/main/CONTRIBUTING.md) covers setup, the one
command that checks everything, and how a change is ported from Effect. Issues labelled
[good first issue](https://github.com/tylergibbs1/pyfect/labels/good%20first%20issue) are a
good place to start. Everyone taking part agrees to the
[Code of Conduct](https://github.com/tylergibbs1/pyfect/blob/main/CODE_OF_CONDUCT.md).

## License

[MIT](https://github.com/tylergibbs1/pyfect/blob/main/LICENSE). pyfect is an independent port and is not affiliated with Effectful
Technologies; Effect is MIT-licensed by its authors.
