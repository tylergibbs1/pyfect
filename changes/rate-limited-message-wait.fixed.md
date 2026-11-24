- A `RateLimited` reason's message, and so its `ChatError`'s, ends with the wait the platform
  asked for, such as `slack.post: RateLimited: ratelimited; retry after 1h`, so a log line of
  the error alone says when to retry. Effect's message leaves it out.
