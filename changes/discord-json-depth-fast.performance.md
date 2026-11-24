- The Discord adapter's check that a gateway frame, interactions request or REST answer nests
  at most 64 deep, made before each parse, no longer walks every character in Python: a body
  with no more than 64 opening brackets (almost every frame) passes after two counts, about
  25 times faster, and any other is counted with the shared `pyfect.chat._json_depth`, about 2
  times faster on Discord's own payloads and 5 times on a 100 MiB frame of brackets. The result
  is the same; `tests/test_chat_json_depth.py` checks it against the old count on random and
  adversarial text. The 100 MiB frame limit is the one Effect's `ws` WebSocket has by default.
