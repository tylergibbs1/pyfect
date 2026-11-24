- `message_storage.DeletesProcessed` is gone: `MessageStorage` requires `delete_processed`, as
  Effect 4.1.4 requires `deleteProcessed` (Effect-TS/effect#10267), so `EncodedStorage` and
  `StorageBase` declare it. A custom storage without it no longer type-checks, where its
  `delete_processed` used to fail with a `PersistenceError`: implement
  `delete_processed(*, entity_type, completed_before, limit)` on it (return `fx.succeed(0)` to
  keep every request, as the noop storage does), and drop any `DeletesProcessed` import or
  `isinstance` check, since every storage now has the method.
