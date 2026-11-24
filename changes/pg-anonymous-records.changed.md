- PostgreSQL: an anonymous record (`ROW(1, 'a')`, `(a, b)`) and a `record[]` read with typed
  fields, as in Effect-TS/effect#10716: `SELECT ROW(1, 'a', NULL, ROW(true, ARRAY[1, 2]))`
  gives `(1, "a", None, (True, [1, 2]))`, where every field was a `str` (`('1', 'a', None,
  '(t,"{1,2}")')`). A record's text has no field types, so such a statement now asks for
  binary results; the first time a session runs a statement, it asks PostgreSQL for the
  statement's column types (one round trip more, once). A field whose type has no binary
  loader reads as UTF-8 text, so enums and `xml` stay strings, but one with a binary layout
  (`point`, `regclass`, a named composite) is now a `SqlError` naming its type OID: cast that
  field to `text` in the query, or register a binary loader for it in `types`. Code that
  parsed the strings reads the values directly instead. A statement keeps text results, and
  string fields, when another of its columns reads differently in binary (`regclass`,
  `float4`, or a type `types` gives only a text loader).
