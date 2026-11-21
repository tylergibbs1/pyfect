- `pyfect.ai.budget` caps what a whole agent run spends: input, output and total tokens, model
  requests, tool calls, and cost through a price function. `effect.pipe(budget.limit(limits))`
  gives the run a budget that every `LanguageModel` request and tool call under it draws from,
  forked fibers, parallel tool calls and sub-agents with models of their own included, and a
  nested limit draws from the ones around it too. Each request reserves its worst case (the
  prompt's estimated tokens plus `max_output_tokens`) before it is sent and settles to the
  response's `usage`, giving back the rest; a tool call is counted before its handler runs. A
  call that doesn't fit fails with `BudgetExceeded` before the provider or handler is called,
  and its concurrent siblings are interrupted. In other agent frameworks these limits
  overshoot when calls run in parallel or nest (8 parallel delegations under a limit of 9 tool
  calls made 16). Effect has no counterpart; the AI budgets page shows it.
