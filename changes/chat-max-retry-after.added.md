- `teams_chat.layer`, `whatsapp_chat.layer` and `telegram_chat.layer` (and `whatsapp_graph_api`'s
  and `telegram_bot_api`'s `make` and `layer`) take `max_retry_after`, passed to
  `chat_adapter.retry_safe`. A 429 asking to wait longer fails the op at once with
  `RateLimited`, its `retry_after` the wait the platform asked for, instead of holding the op,
  and whatever queues behind it, for as long as the platform says; Teams can ask for an hour.
  Without it any wait is waited out, as before and as in Effect. Every adapter now reads a
  `Retry-After` (or Discord's and Telegram's `retry_after`) through one shared parser.
