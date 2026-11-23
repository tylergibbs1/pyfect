- `redis_py`: `Redis.subscribe` returns once the server has confirmed `SUBSCRIBE`, as
  Effect's `NodeRedis` does. It returned once redis-py had sent the command, so a message
  published right after it returned could be lost, and an unanswered `SUBSCRIBE` never
  stalled it.
