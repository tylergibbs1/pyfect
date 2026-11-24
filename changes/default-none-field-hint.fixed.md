- A schema class field whose default is `None` but whose schema refuses `None`
  (`S.field(S.Int, default=None)`) says what it needs when building or encoding the class
  fails on that `None`: "Expected number, and the default None is not one: write
  S.NullOr(schema) for a field that may be None, or S.Union(schema, S.Undefined) to leave the
  key out while it is None". It said only "Expected number".
