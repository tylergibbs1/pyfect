import pyfect as fx
from pyfect import logger

lines: list[str] = []

# A logger that formats entries as logfmt and keeps them (a real program
# would use logger.console_logfmt, console_json or logger.to_logging("app")).
Collect = logger.layer([logger.format_logfmt.map(lines.append)])


@fx.fn
def handle(user_id: str):
    yield from fx.log_debug("dropped: below the minimum level (INFO)")
    yield from fx.log_info("signed in")
    yield from fx.log_warning("password expires soon").with_log_span("check")


program = handle("42").annotate_logs("user_id", "42").pipe(fx.provide(Collect))
fx.run_blocking(program)

assert len(lines) == 2
assert "level=INFO fiber=#" in lines[0] and 'message="signed in" user_id=42' in lines[0]
assert "level=WARN" in lines[1] and "check=" in lines[1]
