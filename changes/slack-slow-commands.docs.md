- Slack docs, "Slow slash commands": a checked example of a command handler that races its
  work against a 2 second budget, answers `defer` when the budget runs out, and sends the
  answer with `Chat.follow_up` from fibers forked into the interactions layer's scope.
