- The chat adapters' JSON depth check, now run by every JSON parse, takes about a tenth of the
  time on a body with many strings (about 1 ms per MB, was about 10 ms): strings without a
  bracket are dropped with `bytes.replace` instead of being matched one at a time.
