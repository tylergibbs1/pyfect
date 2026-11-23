- `durable.layer` with `tool_ledger.guard`: a call whose ledger entry has an intent and no
  result (a crash while its handler ran) gets `ToolOutcomeUnknown` as the ledger's docs say,
  a failed tool result with `on_unknown="tell_model"` and the call's typed failure with
  `"fail"`, and a failing ledger store gives `ToolLedgerError`. Each killed the run with a
  `SchemaError` before, on the first run too: the tool activity stored and read back only the
  tool's own failures. It now stores everything the toolkit's `call_failure_schema` covers.
