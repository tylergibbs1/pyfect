- `S.to_codec_array_from_single` reaches into schema classes (`S.Class`, `S.Error`,
  `S.TaggedClass`, `S.TaggedError`) and declarations' type parameters, as Effect 4.1.4's does:
  a form-urlencoded body or query string whose array field arrives as one key (`missing=amount`)
  now decodes into a class too. A derived `HttpApiClient` reports a declared `S.TaggedError`
  with such a field as that error instead of an `HttpClientError`. The walk now runs on the
  same derivation as `to_codec_string_tree` and `to_codec_json`, which already covered every
  kind of schema.
