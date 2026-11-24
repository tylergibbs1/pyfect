- `IllegalArgumentError`, `NoSuchElementException` and `ExceededCapacityError` have the optional
  `message` Effect's built-in errors take: `IllegalArgumentError("bad arg").message == "bad arg"`,
  and `None` when made without one. Code reading `error.message` on a `skill.from_files` failure,
  say, no longer raises `AttributeError`. `TimeoutException` has a `message` too: by default the
  text Effect's `timeout` writes, `"Operation timed out after '10ms'"`, which is also its string
  form as before. Constructors, equality and string forms are unchanged.
