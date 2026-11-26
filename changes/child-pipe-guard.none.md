- Tests only: `tests/test_child_pipe_guard.py` fails on a test or script that starts a child
  with `stdout=PIPE` or `stderr=PIPE` and never reads that pipe, which hangs once the child
  writes more than the pipe holds.
