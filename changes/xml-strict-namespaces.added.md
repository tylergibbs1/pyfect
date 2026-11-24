- `xml.decode` and `xml.decode_string` take `namespaces="strict"`, which adds the resolved
  `namespace` and `local_name` to each `StartElement` and `EndElement` and fails with a
  `"Syntax"` `XmlError` on a document that is not namespace-well-formed (an undeclared prefix
  fails with `"Unsupported"` when the document has a DOCTYPE). The declarations of open elements
  count against `max_token_size` (Effect #10635).
