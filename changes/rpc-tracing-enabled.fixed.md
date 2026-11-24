- An RPC client sends no span in its requests when the calling fiber has tracing disabled
  (`TracerEnabled`) or `DisablePropagation` set, as Effect's (Effect #10780).
