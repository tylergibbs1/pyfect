- Schema: a check in a field's `Annotated` metadata that can't check the field's type
  (`Annotated[int, S.is_min_length(1)]`, a number check on a `str`) raises `TypeError` where
  the class (or `S.Struct` of a `TypedDict`) is defined, naming the field and the check, as
  Effect's compiler rejects it. It used to define and fail only when a value reached the check,
  so a field with a default, in a union, optional or in a container could carry it unnoticed;
  such a class no longer defines. Give the field a check that fits its type (a length check
  belongs on a string, list or tuple), or move it to the member it fits
  (`Annotated[str, S.is_min_length(1)] | int`). A check on a type it can't try at definition (a
  declaration such as `bytes`, a class) still names the field when it raises on a value.
