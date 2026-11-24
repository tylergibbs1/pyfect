- `LegacyStoreNeedsMigration.automatic`, deprecated in 0.6.9. Read `.state` instead: `automatic`
  was `state != "unconfirmed"`, and `state` (`"pending"`, `"unconfirmed"`, `"ambiguous"` or
  `"unbound"`) says why the server left the store's legacy batches where they are.
