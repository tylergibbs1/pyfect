- `AbortSignal.add_listener` runs its listener as a WHATWG `AbortSignal` does, as in Effect:
  never on a signal that already fired, once for a listener added twice, and not when it is
  removed or added during the abort. Before, it ran at once on a fired signal and ran every
  add. A program that adds cleanup that must run even after the abort uses `on_abort`, which
  runs it at once on a fired signal.
