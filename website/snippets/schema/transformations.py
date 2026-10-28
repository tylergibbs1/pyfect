from datetime import UTC, datetime
from typing import TypedDict

from pyfect import schema as S
from pyfect.schema import transformation as T

# Built-in codecs decode one type from another and encode back.
assert S.decode_unknown_sync(S.NumberFromString)("2.5") == 2.5
assert S.decode_unknown_sync(S.Trim)("  ada ") == "ada"

# decode_to joins two schemas with a function each way: here a price written as
# "12.34" becomes whole cents.
Cents = S.NumberFromString.pipe(
    S.decode_to(S.Int, T.transform(decode=lambda n: round(n * 100), encode=lambda c: c / 100))
)
assert S.decode_unknown_sync(Cents)("12.34") == 1234
assert S.encode_sync(Cents)(1999) == "19.99"


class Event(TypedDict):
    name: str
    at: datetime
    price: int


# Codecs compose inside structs: the wire form is all strings.
EventSchema = S.Struct(Event, name=S.Trim, at=S.DateTimeUtcFromString, price=Cents)
event = S.decode_unknown_sync(EventSchema)(
    {"name": " launch ", "at": "2026-10-27T09:00:00Z", "price": "5.00"}
)
assert event == {"name": "launch", "at": datetime(2026, 10, 27, 9, tzinfo=UTC), "price": 500}
print(S.encode_sync(EventSchema)(event))
