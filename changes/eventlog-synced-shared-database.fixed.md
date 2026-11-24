- Event log SQL servers sharing one database: `EventLog.synced` through one server never
  finished once another server on the database had taken a write. The server reported that
  write as its latest sequence but streamed only the writes it took itself. Both
  `sql_event_log_server_encrypted` and `sql_event_log_server_unencrypted` now stream from the
  table they report from. A server's own writes still reach its clients at once, and other
  servers' writes arrive within `poll_interval` (a new `layer_storage` option, default
  `"1 second"`, positive and finite). Effect's servers stream only their own writes.
