- The Telegram and WhatsApp webhooks count a body's nesting before parsing it about three times
  faster on bracket-heavy bodies: the brackets are packed eight to a byte, so the running sum
  takes one step per eight. The count now lives in one place, `pyfect.chat._json_depth`, shared
  with the Discord adapter.
