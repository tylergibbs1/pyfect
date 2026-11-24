- `pyfect.chat.discord` (Effect's `@effect/chat-discord`, Effect #10581): the Discord adapter
  for `pyfect.chat` over Discord's REST API with no SDK (`discord_rest`), one Gateway shard over
  `pyfect.socket` (`discord_gateway`, which needs the `websockets` extra) that resumes from a
  `ShardStateStore` and replays an event a `DispatchHook` refused, the HTTP interactions
  endpoint (Ed25519 signatures checked through `Signature`, which needs the `crypto` extra, a
  five minute timestamp window, a body limit, typed parsing at the route), buttons, selects,
  modals and slash commands, `with_post_options` to choose who a post notifies, and the pure
  `normalize` and `normalize_interaction`. Docs: [Discord](https://pyfect.dev/docs/chat-discord).
