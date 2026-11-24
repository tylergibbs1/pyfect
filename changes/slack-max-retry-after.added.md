- `slack_chat.layer` (and `slack_web_api`'s `make` and `layer`) take `max_retry_after`, as the
  other adapters' layers do: a 429 asking to wait longer fails the op at once with
  `RateLimited`, its `retry_after` the wait Slack asked for. Without it any wait is waited out,
  as before and as in Effect.
