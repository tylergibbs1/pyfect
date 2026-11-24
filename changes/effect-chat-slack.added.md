- `pyfect.chat.slack` (Effect's `@effect/chat-slack`, Effect #10581 with #10749): the Slack
  adapter for `pyfect.chat` over the Web API with no SDK, the Events API and Interactivity
  routes (`v0` signatures checked in constant time through `Mac`, a five minute timestamp
  window, a body limit, typed parsing at the route), slash commands and modals, native
  streaming with Slack's stop button, `with_post_options` to choose who a post notifies, and
  the pure `normalize` and `normalize_interaction`. Docs: [Slack](https://pyfect.dev/docs/chat-slack).
