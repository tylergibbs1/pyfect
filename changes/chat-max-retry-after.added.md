- `teams_chat.layer` and `whatsapp_chat.layer` (and `whatsapp_graph_api.make` and `layer`) take
  `max_retry_after`. A 429 whose `Retry-After` is longer fails the op at once with `RateLimited`,
  its `retry_after` the wait the platform asked for, instead of holding the op, and whatever
  queues behind it, for as long as the platform says; Teams can ask for an hour. Without it any
  wait is waited out, as before and as in Effect.
