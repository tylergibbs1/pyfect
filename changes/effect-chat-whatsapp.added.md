- `pyfect.chat.whatsapp` (Effect's `@effect/chat-whatsapp`, Effect #10581): the WhatsApp
  Cloud API adapter for `pyfect.chat` over the Graph API with no SDK. The webhook answers
  Meta's subscription check (verify token compared in constant time) and checks
  `X-Hub-Signature-256` through `Mac`, with a body limit and a 64 level nesting cap. Markdown
  renders to WhatsApp's formatting without ever growing the text, in linear time; replies
  use reply buttons, link buttons and lists; `send_template` writes outside the 24 hour
  window; and `normalize`, `delivery_key` and `update_key` serve a consumer's own transport.
  Docs: [WhatsApp](https://pyfect.dev/docs/chat-whatsapp).
