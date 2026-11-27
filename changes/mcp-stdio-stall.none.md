- CI only: a job that runs server tests loads its container images before the tests start
  and waits for the disk to write them; a test never loads or pulls one. Loaded mid-run, the
  images' GBs of layers slowed a shard's first three minutes about fivefold, and the MCP
  example's subprocess, importing pyfect, didn't answer within its test's 5 s timeout.
