- `openai_compat`: a PDF given as a URL (a `Url`, or an `http(s)://` string) fails with an
  `InvalidUserInputError` before any request, as in Effect 4.1.4 (Effect-TS/effect#10514): Chat
  Completions takes no PDF URL. A `Url` was sent as text and a URL string was dropped. Pass the
  PDF's bytes, base64 data or an uploaded file's id instead.
