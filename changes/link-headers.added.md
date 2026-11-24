- `Link` headers (RFC 8288): `headers.Link`, `headers.parse_link`, `headers.format_link`,
  `http.schema.LinkHeaderFromString`, and `response.links` / `response.link(res, rel)`, which
  resolve targets against the response URL and skip anchored links. `Headers.append`,
  `HttpClientRequest.append_header` and `HttpServerResponse.append_header` add to a header
  without replacing it (Effect #10817).
