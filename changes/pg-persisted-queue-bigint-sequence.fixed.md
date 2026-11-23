- The PostgreSQL `PersistedQueue` store (`make_store_sql` / `layer_store_sql`) keeps taking
  offers past 2,147,483,647 rows. Migration `0002` widened the `sequence` column to `BIGINT`
  but left its `SERIAL` sequence a 32-bit integer, so offers failed once the sequence reached
  its maximum. A new PostgreSQL-only migration, `0004_widen_sequence`, widens the sequence;
  it runs once when the store starts. Port of Effect #10781, whose migration is `0003`;
  pyfect's `0003` is already `0003_exact_ids`.
