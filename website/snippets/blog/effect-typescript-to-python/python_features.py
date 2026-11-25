from dataclasses import dataclass

import pyfect as fx
from pyfect.cause import Die, Fail
from pyfect.run import unwrap_group


@dataclass
class Overdrawn(fx.TaggedError):
    balance: int


class AuditLogDown(Exception):
    pass


def withdraw(amount: int) -> fx.Effect[int, Overdrawn]:
    return fx.succeed(100 - amount) if amount <= 100 else fx.fail(Overdrawn(100))


# Exit.match / Cause.match in TypeScript; Python's match takes them apart.
def describe(exit: fx.Exit[int, Overdrawn]) -> str:
    match exit:
        case fx.Success(left):
            return f"{left} left"
        case fx.Failure(fx.Cause([Fail(Overdrawn(balance))])):
            return f"only {balance} available"
        case fx.Failure(fx.Cause([Die(defect), *_])):
            return f"bug: {defect!r}"
        case fx.Failure(cause):
            return f"other: {cause!r}"


print(describe(fx.run_blocking_exit(withdraw(30))))
print(describe(fx.run_blocking_exit(withdraw(300))))

# A failure whose cleanup also crashed holds two errors. unwrap_group raises them
# as one ExceptionGroup, so except* handles each.
crashed = fx.run_blocking_exit(withdraw(300).ensuring(fx.die(AuditLogDown())))
try:
    unwrap_group(crashed)
except* Overdrawn as group:
    print("typed error:", group.exceptions)
except* AuditLogDown as group:
    print("defect:", group.exceptions)

# acquire_release as a context manager for code that isn't an effect.
session = fx.acquire_release(
    fx.sync(lambda: print("session opened") or "session-1"),
    lambda _s, exit: fx.sync(lambda: print(f"session closed after {type(exit).__name__}")),
)
with fx.managed(session) as s:
    print("using", s)
