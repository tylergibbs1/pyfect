- `http.live_server` takes `websocket_high_water_mark`, the inbound WebSocket bytes that may
  wait for a reader's pull before the server stops reading the connection (64 KiB by default),
  as Effect 4.1.5's `websocket.highWaterMark` (#10628). An empty message counts as one byte, so
  a client sending only empty messages is paused too.
