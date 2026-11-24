- A dispatch the Discord `DispatchHook` refused is no longer lost when the next dispatch was
  already read: the shard used to hand that one to the hook and store its sequence, so the
  RESUME asked for what came after it. As in dfx (which Effect's Discord adapter runs on), once
  the shard drops a connection it skips whatever is still queued from it until the next HELLO,
  sends no heartbeat in between, and stores a `READY`'s session only after the hook took it.
