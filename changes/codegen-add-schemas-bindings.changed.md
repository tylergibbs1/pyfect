- `codegen.Module.add_schemas` returns the schemas' bindings (a `Mapping[str, DeclarationBinding]`
  by the names given), as Effect's `addSchemas` returns its `ReadonlyMap`, instead of the module.
  Instead of `m.add_schemas(...).print()`, write `m.add_schemas(...)` and then `m.print()`;
  instead of chaining two calls, call `add_schemas` on the module twice.
