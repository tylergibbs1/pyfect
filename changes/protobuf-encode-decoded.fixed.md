- `protobuf.message.encode`, `get_extension` and `set_extension` accept a message `decode`
  or `set_extension` returned (`Message`, unknown fields included) as well as a mapping of
  field names, so a decode, edit, encode round trip type-checks without an ignore.
