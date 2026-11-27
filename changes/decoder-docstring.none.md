- Docs only: `LanguageModel._decoder`'s docstring says a call to a tool outside the
  toolkit fails the parts decode (a `SchemaError`, as in Effect), not with `ToolNotFoundError`.
