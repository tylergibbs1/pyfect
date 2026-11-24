- The WhatsApp adapter waits out a rate-limited answer's `Retry-After` before it sends again, as
  the Teams and Slack adapters do, and keeps it as the `RateLimited` error's `retry_after`. It
  ignored the header and retried after its own backoff from half a second, while Meta still
  refused.
