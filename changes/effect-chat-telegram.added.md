- `pyfect.chat.telegram` (Effect's `@effect/chat-telegram`, Effect #10581): the Telegram Bot
  API adapter for `pyfect.chat` with no SDK. The webhook compares the secret-token header in
  constant time before reading the body, with a body limit and a 64 level nesting cap, and
  `layer_polling` runs `getUpdates`, confirming each update only after it ran. Markdown is
  escaped into rich messages that hold no raw HTML, image or non-web link, in linear time;
  entity offsets are UTF-16 units; files, buttons and commands sit behind `unverified_*`
  options; and `normalize`, `normalize_interaction` and `delivery_key` serve a consumer's own
  transport. Docs: [Telegram](https://pyfect.dev/docs/chat-telegram).
