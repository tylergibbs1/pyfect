- Tests only: `uv run python tests/_parity_counts.py --write` rewrites docs/PARITY.md's
  hand-kept counts (§4's class counts, §5's row counts, the open title total) from what they
  count, the §4 tests run before every push, and a §4 row split by an unescaped `|` is named
  with its line.
