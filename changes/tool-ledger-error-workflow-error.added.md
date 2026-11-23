- AI tool ledger: `ToolLedgerError` is a schema, so a durable workflow can list it in its
  `error=` as it does `ToolOutcomeUnknown`
  (`error=S.Union(tool_ledger.ToolOutcomeUnknown, tool_ledger.ToolLedgerError)`) and a
  failing ledger store reaches the workflow's caller as a typed error. Its `cause` comes back
  as an `ErrorInstance`.
