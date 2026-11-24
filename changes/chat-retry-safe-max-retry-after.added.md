- `chat_adapter.retry_safe` takes `max_retry_after`: a `retry_after` longer than it is not
  waited out, and the `ChatError` comes back at once with the wait on it, for the caller to
  decide. The default, `None`, waits out any wait, as Effect's `retrySafe` does.
