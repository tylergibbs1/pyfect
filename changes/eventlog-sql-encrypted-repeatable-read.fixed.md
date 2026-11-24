- The SQL encrypted event log server works on a PostgreSQL database whose transactions default
  to REPEATABLE READ or SERIALIZABLE (`default_transaction_isolation`). Of two servers starting
  together on a new database, one died with `could not serialize access due to concurrent
  update` while recording the upgrade, and had it got past that, would have stored a second
  remote id: its read after waiting for the other's lock still saw the empty table. Writes to
  one store from two servers failed the same way, as defects. The storage now runs every
  transaction at READ COMMITTED on PostgreSQL, which its locks rely on. MySQL (REPEATABLE READ
  by default) and SQL Server were not affected: their locking reads see the latest rows.
