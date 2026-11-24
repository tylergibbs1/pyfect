- CSV decoding with `headers=True` reads an empty cell of an optional field of an `S.Class`, or of
  a union of classes, as a missing key, as it already did for structs (Effect #10759). Classes
  also count as structs when HttpApi finds the names of path parameters, documents the file
  fields of a multipart payload as binary in OpenAPI, and refuses the reserved event name in a
  `StreamSse` events schema: each walk now reads a class's fields through
  `schema.ast.encoded_objects`.
