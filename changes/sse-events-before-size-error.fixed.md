- `sse.decode` emits the events it parsed before an event that is too large, then fails with
  `SseError` (`EventTooLarge`). When a complete event and an oversized one came in the same
  chunk, the complete event was dropped.
