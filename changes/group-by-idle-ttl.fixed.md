- `Stream.group_by` and `group_by_key` with a finite `idle_time_to_live` no longer lose values.
  A group could expire while a value was on its way into it: with a zero TTL every value was
  dropped, and a group whose reader was slower than its TTL ended early, so the rest of its
  key's values went to a new group. A group now stays open until each offer into it has been
  accepted or cancelled.
