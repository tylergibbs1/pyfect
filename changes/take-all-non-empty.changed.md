- `take_all` on `Queue` / `Dequeue`, `TxQueue` / `TxDequeue` and `PubSub` subscriptions
  returns a non-empty tuple (`tuple[A, *tuple[A, ...]]`), as Effect's `NonEmptyArray`, where it
  returned a `list` typed `list` or `Sequence`. Code that mutates the result, or annotates it
  as `list`, should copy it with `list(...)`; code that indexes it or iterates over it is
  unchanged, and `items[0]` is now typed as present.
