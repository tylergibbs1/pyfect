- `telegram_chat.escape_markdown(text)` and `teams_chat.escape_markdown(text)` turn text a user
  wrote, such as a display name, into Markdown that shows it as typed, so a name like
  `[x](https://evil.example)` is no longer a live link in a post. A dogfood app had that
  injection. WhatsApp needs none: it has no link markup and no escape character, which its docs
  page now says.
