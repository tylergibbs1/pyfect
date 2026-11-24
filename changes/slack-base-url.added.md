- `slack_chat.layer` takes `base_url`, passed to its `slack_web_api.layer` (default
  `https://slack.com/api`), so a GovSlack app can use `https://slack-gov.com/api`. Effect's
  `SlackChat.layer` has no such option; its `SlackWebApi.layer` takes `baseUrl`, which
  `slack_web_api.layer(base_url=...)` already matched. Docs: [Slack](https://pyfect.dev/docs/chat-slack).
