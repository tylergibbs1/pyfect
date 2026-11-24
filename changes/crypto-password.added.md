- `pyfect.crypto.password` stores passwords as PHC strings: the `Password` service from
  `password.layer(algorithm=...)` hashes with Argon2id or PBKDF2 from `kdf`, verifies against
  the algorithm and salt the stored hash records, and reports with `needs_rehash` when a hash
  no longer matches the configured algorithm. `password.decode` and `password.encode` convert
  between PHC strings and `PasswordHash` values. No new dependency: Argon2id comes from the
  existing `crypto` extra through `native.layer` (Effect #10734).
