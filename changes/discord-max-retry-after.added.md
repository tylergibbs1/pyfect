- `discord_chat.layer` takes `max_retry_after`: a 429 asking to wait longer fails `RateLimited`
  at once, its `retry_after` on the error, instead of holding the request (and whatever queues
  behind it) for as long as Discord asks; its shared limits can ask for over 20 minutes. By
  default any wait is still waited out, as in Effect, whose Discord adapter and dfx's REST
  client wait without a bound.
