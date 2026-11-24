- The JSON depth check that every JSON parse runs costs about half as much on large text: a
  50 MB array of small objects about 1.2 ms per MB (was 1.8), strings full of brackets and
  escaped quotes about 2 ms (was 3.7), and one long string next to nothing (was 0.5). Escapes
  go through `codecs.escape_decode` in one pass instead of two `bytes.replace` calls, and text
  over 65,536 characters is searched for at most 513 opening brackets instead of counted.
