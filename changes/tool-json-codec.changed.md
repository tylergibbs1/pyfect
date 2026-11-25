- AI tools speak JSON at both ends, as in Effect 4.1.4 (Effect-TS/effect#10332,
  Effect-TS/effect#10362). A toolkit decodes a call's parameters with the JSON codec of the
  tool's parameters schema, and a result's `encoded_result` is the JSON encoding of its
  success or failure schema: a `DateTimeUtc` is ISO text and a `BigInt` a string of digits,
  where it was the plain encoding (a `datetime`, an `int`). So a tool whose parameters are
  not plain JSON, a `DateTimeUtc` field say, now works when a model calls it (Anthropic,
  OpenAI and OpenRouter hand the toolkit the parameters' JSON form, and `needs_approval`
  decodes them the same way), and a dynamic tool without a `success` schema fails with
  `ToolResultEncodingError` when its handler returns a value JSON has no form for.
  `response.all_parts(toolkit)` encodes a locally handled tool's results with the same JSON
  codec; a provider-executed tool's keep the provider's payload. What to do instead: a
  direct `WithHandler.handle(name, params)` caller passes the parameters' JSON encoding
  (`S.encode_unknown_sync(S.to_codec_json(tool.parameters_schema))(params)`), and code that
  read `encoded_result` expecting the plain encoding decodes it with
  `S.to_codec_json(tool.success_schema)`. A dynamic tool whose handler returns such values
  declares a `success` schema. The tool ledger and `ai.durable` store the JSON encoding too,
  so a record of such a result written by 0.6.x no longer decodes: finish those runs on
  0.6.x before upgrading, or clear their records.
