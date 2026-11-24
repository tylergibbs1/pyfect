- `pyfect.chat.teams` (Effect's `@effect/chat-teams`, Effect #10581 with #10758): the
  Microsoft Teams adapter for `pyfect.chat` over the Bot Framework Connector with no SDK, and
  the messaging endpoint, which checks each Bot Framework token (RS256 only, a key endorsed
  for `msteams` from the OpenID metadata's key set, issuer, audience, expiry with five
  minutes of skew, and the token's `serviceurl`, channel and tenant) and bounds the body.
  Buttons, dialogs, agent commands, `start_thread` and downloads wait behind `Unverified`.
  Locating mentions in an activity stops after scanning 64 times the text's length, so an
  activity with many mention entities missing from its text costs linear time. Docs:
  [Microsoft Teams](https://pyfect.dev/docs/chat-teams).
