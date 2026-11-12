from datetime import UTC, datetime

from pyfect.date_time import intl, zone_named

# Effect's DateTime.format: what Intl.DateTimeFormat prints under Node.
moment = datetime(2026, 7, 4, 18, 5, 9, tzinfo=UTC)
london = zone_named("Europe/London")
assert london is not None

print(intl.format_utc(moment, locale="en-US"))
print(intl.format_utc(moment, locale="en-GB", date_style="full", time_style="long"))
print(intl.format(moment.astimezone(london), locale="ja-JP", date_style="full", time_style="long"))
print(intl.format_utc(moment, locale="ar-EG", year="numeric", month="long", day="numeric"))
print(intl.format_utc(moment, locale="fa-IR", date_style="medium"))
# format_utc is UTC even with a time_zone, as Effect's formatUtc; format_local
# takes it.
print(intl.format_utc(moment, locale="de-DE", time_zone="Asia/Tokyo", time_style="short"))
print(intl.format_local(moment, locale="de-DE", time_zone="Asia/Tokyo", time_style="short"))

# A style with a field option is a TypeError, as in Intl.
try:
    intl.format_utc(moment, date_style="short", hour="numeric")
except TypeError as error:
    print("TypeError:", error)
