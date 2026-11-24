- Schema: a schema class field whose default is not a value of its schema's type
  (`n: int | None = S.field(S.Int, default=None)`, which pyright accepts because a schema is
  covariant, as Effect's `Codec` is) raises `TypeError` where the class is defined, naming the
  field, as Effect's compiler rejects such a constructor default. It used to define and fail
  each time the class was built without that field. Give the field a schema that takes the
  default (`S.NullOr(S.Int)`, or `S.Union(S.Int, S.Undefined)` to leave the key out while it
  is `None`) or a default of its type. The default's checks still run at construction, and a
  schema naming a class defined further down is still checked on first use.
