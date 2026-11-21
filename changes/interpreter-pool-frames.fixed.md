- `interpreter_pool` with the `PYFECT_WARN_BLOCKING` watchdog no longer corrupts memory on
  Python 3.14 before 3.14.8. There `sys._current_frames()` also made frame objects for the
  pool's subinterpreters, from the wrong interpreter's allocator (python/cpython#158364), and
  the process died with `free(): invalid pointer` or `double free or corruption`. The watchdog
  now skips its sample while a pool's subinterpreter runs code.
