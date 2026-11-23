- `WithHandler.call_failure_schema(name)`: every failure a call of the tool can give its
  caller, as a failed result or an error. `pyfect.ai.durable` stores tool results with it; a
  toolkit wrapping another (as `tool_ledger.guard` does) extends the wrapped one's.
