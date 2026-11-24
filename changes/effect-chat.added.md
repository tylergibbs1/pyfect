- `pyfect.chat` (Effect's `effect/chat`, Effect #10581 with #10748 and #10750): the `Chat`
  service that posts, edits, reacts and streams to any registered platform adapter, typed
  `ChatError` reasons with a fixed retry value, `chat_markdown.post` and `stream` (Markdown
  split to a platform's limits at block boundaries, code fences closed and reopened, native
  streaming or post-then-edit, failures that say what was posted), typed buttons, selects,
  modals and slash commands with a 3 second deadline (`chat_interaction`), the `ChatHandler`
  event layer, and `chat_test`: an in-memory platform plus the conformance suite adapters
  run. Docs: [Chat](https://pyfect.dev/docs/chat).
