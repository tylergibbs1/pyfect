- `codegen.Module.add_schemas` no longer refuses a module that also has declarations, in either
  order, as Effect 4.1.5's `addSchemas` allows: each schema declares its name (`User1` when
  `User` is taken) and its type's (`UserType`), its imports merge with the module's, and
  `print` writes declarations after what they read. The new `bindings=` dict gets each schema's
  binding by the name given, for `define` to read, and `type_only=True` writes only the types.
  A module of schemas alone prints as before.
