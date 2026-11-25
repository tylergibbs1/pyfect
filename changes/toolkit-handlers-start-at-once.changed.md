- A toolkit's tool handler starts as soon as its call is handled, not in a later scheduler
  round, and its last result reaches the stream once it exits, as in Effect 4.1.5. So an MCP
  `tools/call` with a toolkit is answered without waiting a round. One effect you can see:
  `stream_text(...).take(n)` now starts the handlers of the tool calls the model sent, even
  ones the stream stops before. It used to start none. To keep a handler from running, stop
  the stream before its tool call, or leave the tool out of the toolkit.
