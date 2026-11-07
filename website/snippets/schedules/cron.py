import itertools
from datetime import UTC, datetime

import pyfect as fx
from pyfect import cron, schedule, testing

# Five fields (minute hour day month weekday), or six with seconds first.
# `parse` returns a Result; `parse_unsafe` raises on a bad expression.
weekdays = cron.parse_unsafe("30 9 * * MON-FRI", "Europe/Berlin")
now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)  # a Friday

print("next:", cron.next(weekdays, now))
for run in itertools.islice(cron.sequence(weekdays, now), 1, 3):
    print("then:", run)
print("matches:", cron.match(weekdays, datetime(2026, 11, 9, 8, 30, tzinfo=UTC)))

match cron.parse("61 * * * *"):
    case fx.Ok():
        print("parsed")
    case fx.Err(error=error):
        print("error:", error.message)

# `schedule.cron` waits for each matching time. On the test clock, an hour
# of every-15-minutes runs takes no real time.
ticks: list[str] = []
quarter_hours = schedule.cron("*/15 * * * *", "UTC").up_to(times=3)
record = fx.clock.now().map(
    lambda s: ticks.append(datetime.fromtimestamp(s, UTC).strftime("%H:%M"))
)


@fx.gen
def program():
    yield from testing.set_time(now.timestamp())
    fiber = yield from record.repeat(quarter_hours).fork()
    yield from testing.adjust("1 hour")
    yield from fiber.join()


testing.run_test(program.or_die())  # an invalid expression would fail the schedule
print("ticks:", ticks)
