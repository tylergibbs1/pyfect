- Schema: a schema class whose field annotation has no schema (`value: complex`) raises
  `TypeError` where the class is defined, naming the field (`Unsupported.value: No schema for
  the annotation ...`), instead of on first use. A module that defines such a class without
  ever using it no longer imports: give the field its schema with `S.field(...)`. An
  annotation naming something not defined yet (the class itself, a class further down) is
  still derived on first use.
