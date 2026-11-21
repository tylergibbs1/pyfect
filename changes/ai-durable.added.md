- `pyfect.ai.durable` makes an agent loop durable without changing its code: provide
  `durable.layer` over the `LanguageModel` a workflow uses, and every model request and tool
  call inside the workflow runs as one of its activities, named by its place in the run
  (`pyfect/ai/<n>/model`, `pyfect/ai/<n>/tool/<i>`), so a crashed run resumes without calling
  the model or a tool again. Each step stores its output and a hash of its request, never the
  prompt, so history grows with the turns and not with the conversation (on SQLite, about 710
  bytes a turn: 7.5 kB at 10 turns, 72 kB at 100). A replay whose request hashes differently, because
  the code changed under a running execution, dies with `RequestDiverged` instead of reusing
  the stored answer. A streamed request is stored once its stream ends and reaches the caller
  as one chunk, on the first run and on replays. Replayed steps spend a budget made in the
  workflow's body again, so a resumed run stops where an uncrashed one does, and tools behind
  the tool ledger never run twice. Other frameworks' durable agents overflowed their history
  (Temporal #1890, terminated at call 53 of 100) or replayed changed requests from stale
  results. `explore.activity_crashes` takes `at=` to split a long sweep into parts.
