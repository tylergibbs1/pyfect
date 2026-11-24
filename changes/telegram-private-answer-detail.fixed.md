- A Telegram command answer refused for being private (`chat_interaction.respond` and `defer`
  default to `visibility="ephemeral"`, which the adapter has no way to send) fails `Unsupported`
  with detail `ephemeral`, so the `chat_interaction` log line reads
  `telegram.respond: Unsupported: ephemeral` instead of a bare `Unsupported` that did not say what
  was missing. The Telegram docs say to answer with `visibility="public"`.
