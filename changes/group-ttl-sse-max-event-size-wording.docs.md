- `Stream.group_by` and `group_by_key` no longer say a group ends after `idle_time_to_live`
  only when nobody reads it: the time counts from the last value the group took, so a group
  being read still ends when no new value comes. `sse.make_parser`, `sse.decode` and the
  streams guide now say `max_event_size` bounds only the event left unfinished at the end of a
  chunk; a complete event that arrives in one read is accepted at any size.
