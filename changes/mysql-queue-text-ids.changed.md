- SQL `PersistedQueue` on MySQL: the `id` and `queue_name` columns are text again,
  `VARCHAR(255)` as in Effect, in `utf8mb4_0900_bin` so ids and queue names still compare
  exactly (case, accents and trailing spaces count). `0003_exact_ids` (0.6.4) had made them
  `VARBINARY(1020)`, so a pyfect from before 0.6.4 sharing the table, during a rolling upgrade
  or after a downgrade, handed its handlers `meta.id == "b'job'"`, breaking idempotency keys.
  The MySQL-only migration `0005_exact_text_ids` converts the table on start and keeps its
  rows (`0004` is PostgreSQL's `widen_sequence`). An `offer` whose id or queue name has more
  than 255 characters now fails with a `PersistedQueueError`, where up to 1020 bytes fitted:
  shorten such ids, or hash them to a fixed length, before offering. A table already holding
  a longer one stops the migration with an error giving how many rows: delete or shorten
  those rows, then start again.
