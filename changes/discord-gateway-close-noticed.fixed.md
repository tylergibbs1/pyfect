- The Discord gateway's websocket (`discord_gateway.layer_ws`) reconnects as soon as Discord
  closes the connection, instead of only at the shard's next write, up to a heartbeat interval
  (about 41 seconds) later: each connection's read and write loops now end at the first exit
  (`race_first`), not the first success. dfx, which Effect's Discord adapter runs on, reads in
  the connection's own loop and never had the delay. `tests/test_chat_race_guard.py` keeps
  `race` out of the chat adapters.
