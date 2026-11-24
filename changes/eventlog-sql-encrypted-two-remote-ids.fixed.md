- A SQL encrypted event log server whose remote id table holds several ids (servers that
  started together on a new database under 0.6.22 or earlier, or under Effect, could each
  store one) now always serves the lowest in byte order and logs a warning naming the table
  and how many ids it holds. It served whichever row the database returned first, so servers
  could disagree. Clients that synced under another id sync again once. The event log docs
  show how to delete the extra ids:
  [One remote id per database](https://pyfect.dev/docs/eventlog#one-remote-id-per-database).
