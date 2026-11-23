- OpenAI `stream_text` keeps the model's refusal explanations. A refused message's
  `text-end` part carries them in `metadata["openai"]["refusal"]`, joined by a blank line when
  there are several, and a prompt built from the streamed parts keeps them in the text part's
  options. Before, a streamed refusal reached the caller as empty text with no explanation;
  `generate_text` already kept it (Effect-TS/effect#10702).
