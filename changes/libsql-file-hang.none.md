- Tests only: SQLite files a test opens commit without fsync unless the test is marked
  `sqlite_fsync` (`tests/_sqlite_sync.py`), so a CI runner's slow disk flush no longer times
  out the libSQL local-file round trip or any other test of logic over a file.
