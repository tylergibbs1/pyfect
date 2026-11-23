- Amazon Bedrock: a conversation whose earlier tool call returned a list, number or boolean
  no longer fails. Such a result was sent as a Converse `json` block, which Bedrock rejects
  for anything but an object; it now goes as its JSON text. Object results are still `json`
  blocks, and a `None` result is still empty text (Effect-TS/effect#10767).
