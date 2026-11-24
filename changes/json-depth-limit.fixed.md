- JSON from a peer is refused once it nests more than 512 arrays and objects deep, before it is
  parsed, with the error malformed JSON gets there: a 400 from `HttpServerRequest.json` and
  HttpApi payloads, a `SchemaError` from `Schema.from_json_string`, `NdjsonDecodeError` from the
  RPC serializations, a parse error from MCP, `"InvalidJson"` from `ndjson` decoders. Python 3.14's
  `json.loads` reads about a hundred thousand levels (3.13's about ten thousand), and code that
  walked such a value recursively raised `RecursionError`, a defect: an AI provider's error body
  or stream event, a reviver given to `schema_body_json` (a 500), `==` on the value. Effect's
  `JSON.parse` has no limit. `json_array` keeps its own `max_depth` (default 1000), and the chat
  adapters their tighter limits (Teams 128, the others 64).
