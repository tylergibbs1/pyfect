- Tool ledger and durable agents: a bare-id ledger record from 0.6.22 or earlier answers every
  later workflow execution that reuses its `tool_call_id`, with the SQL statement that clears
  those rows once no older execution is running; each guarded call in a workflow does one extra
  lookup for it. With `on_unknown="fail"`, `ToolOutcomeUnknown` reaches a workflow's caller only
  when its `error=` schema lists it, and pyright rejects a missing one at `to_layer`.
