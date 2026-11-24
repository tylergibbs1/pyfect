- On Windows the process spawner refuses a `.bat` or `.cmd` file (any case, and ignoring the
  trailing dots and spaces Windows drops) unless the command sets `shell`, as Node, and so
  Effect, has since CVE-2024-27980: `cmd.exe` parses a batch file's arguments again, so an
  argument could run another command. The spawn dies with `OSError(EINVAL)`, Node's
  `spawn EINVAL`, where it used to run the file; a `ProcessWorker` whose `executable` is a
  batch file raises it from `start`. To run a batch file, pass the whole script as the command
  with `shell=True`, quoting any value in it for `cmd.exe` yourself, or call the program the
  batch file wraps directly. A guard requires every place pyfect starts a process to go
  through the check.
