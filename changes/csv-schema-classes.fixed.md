- `csv.decode_schema`, `decode_schema_string`, `encode_schema` and `encode_schema_string` accept
  schema classes (`S.Class`, `S.Error`, `S.TaggedClass`, `S.TaggedError`) and unions of them,
  as Effect 4.1.4's `Csv` does, instead of raising "Csv: cannot verify string cells for Class".
  The structured-output codecs (`to_codec_openai`, `to_codec_anthropic`) also rewrite a class's
  fields now (a tuple field is sent as an object, as in a struct), so a class with such a field
  decodes from the model's output. Walks over a schema's encoded side read a class as its
  fields' struct through the new `schema.ast.encoded_structure`, as Effect's `toEncoded` gives it.
