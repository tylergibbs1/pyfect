- `mcp_server.toolkit` and `register_toolkit` send a tool's `to_model_output` parts as a
  successful call's `content`, keeping the encoded result as `structuredContent`, as in
  Effect 4.1.5 (Effect-TS/effect#10740). Text parts are text blocks; an `image/*` (and from
  2025-03-26 an `audio/*`) file given as bytes, base64 or a base64 data URL is an image or
  audio block; a file at an `http(s)` URL is a `resource_link` from 2025-06-18, else its URL as
  text; any other file is `tool_model_output_to_text`'s placeholder. A string result keeps no
  `structuredContent` before 2026-07-28. Before, MCP ignored `to_model_output` and sent the
  result's JSON text. What to do instead: a client that read the JSON text of such a tool's
  `content` reads `structuredContent`; to keep sending the JSON text, make the tool without
  `to_model_output` for MCP, or give it a content mapper (`mcp_server.tool_content`), which
  takes precedence.
