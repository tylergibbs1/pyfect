- `slack_chat.escape_markdown(text)` turns text a user wrote, such as a display name, into
  Markdown that shows it as typed through the Slack adapter: `<!channel>`, `<@U1>` and
  `<http://evil|click>` become entities, so no token in it notifies whatever
  `SlackPostOptions` allow, and `*bold*`, `_x_`, `~x~`, `` `x` `` and links are backslash-escaped.
