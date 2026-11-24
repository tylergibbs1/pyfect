- `telegram_chat.layer_polling` gives each `getUpdates` its long poll plus 3 seconds to answer,
  then gives it up and retries it with `chat_adapter.retry_safe`'s backoff. A connection that died
  without a reset (a NAT entry gone, a proxy that stopped answering) left the call waiting forever,
  and the bot never read another update; Effect's adapter has the same hang. The layer's first
  call has the 3 seconds too. `TelegramBotApiService.call` takes a `timeout` for this: a request
  without an answer by then fails `Transport` with detail `timeout`.
