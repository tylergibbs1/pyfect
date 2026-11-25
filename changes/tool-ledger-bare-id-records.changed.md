- `tool_ledger.guard` inside a workflow reads only the call's `<execution id>/<tool_call_id>`
  record: records written by 0.6.22 and earlier under the bare `tool_call_id` are no longer
  read, and the extra lookup each guarded call in a workflow made for them is gone. What to
  do instead: let workflows still in flight from 0.6.22 finish on 0.6.x before upgrading, or
  clear their ledger records (`DELETE FROM effect_ai_tool_ledger WHERE id NOT LIKE '%/%'` in
  the default table, once no guarded call outside a workflow will be replayed); otherwise
  their tool calls run again. A bare-id record cannot be moved to its scoped key, since it
  does not record which execution wrote it.
