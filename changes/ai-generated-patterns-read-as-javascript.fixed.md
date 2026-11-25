- AI providers' generated schemas: a pattern's `\s` and `\S` match JavaScript's whitespace
  (U+FEFF is whitespace; U+001C-U+001F and U+0085 are not), as Effect's do, where they used
  Python's. OpenAI's `LiveCallReferRequest.target_uri` accepted a value of only U+FEFF.
