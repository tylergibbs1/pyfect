- A schema `codegen.Module(reserved).add_schemas` adds no longer takes a name in `reserved`,
  which the surrounding code owns: `Module(["Client"])` declares the schema `Client` as
  `Client1`, as `declare` does.
