- `telegram_chat.layer_webhook` hands commands and button clicks to the `chat_interaction.Handler`
  its layer was given. It read the handler from each request's context, where it is not, so a
  command fell through to the `ChatHandler` as an ordinary message and a click was answered and
  dropped, with nothing logged; polling, whose fiber is forked in the layer, worked. Both
  transports now take the `ChatHandler` and the `chat_interaction.Handler` from the layer when it
  is built, and run updates through one function that is given both.
