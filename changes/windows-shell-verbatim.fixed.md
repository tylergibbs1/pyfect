- A command with `shell=True` runs on Windows. Its `cmd.exe /d /s /c "<script>"` line went to
  `subprocess` as a list, which escaped the script's quotes, so `cmd.exe` ran nothing; it is
  passed verbatim now, as Node's `windowsVerbatimArguments` does.
