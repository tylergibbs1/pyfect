- `pyfect.protobuf`, Effect's `effect/protobuf` in pure Python (Effect #10554, #9454): the
  wire `reader` and `writer`; `descriptor.make` and `descriptor.from_file_descriptor_set`,
  which resolve `protoc`'s descriptors (proto2, proto3 and editions 2023 to 2026); and
  `message.encode`, `decode`, `get_extension` and `set_extension` for messages as dicts,
  with unknown fields kept. `descriptor_proto` has the types and descriptors of
  `google/protobuf/descriptor.proto`. Decoding bounds nesting (`max_depth`, 100 by default)
  and varint lengths, and takes an optional `max_size`. The OTLP protobuf exporter now
  writes with `writer.ProtobufWriter`, and log record trace and span ids may be bytes.
