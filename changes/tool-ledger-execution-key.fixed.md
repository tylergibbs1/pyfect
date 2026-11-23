- `tool_ledger.guard` keys a call made inside a workflow by `<execution id>/<tool_call_id>`,
  so two executions on one database whose model reuses an id no longer answer the second
  one's call from the first one's record. Outside a workflow the key is still the bare id,
  and a record an earlier release stored under the bare id still answers the call.
