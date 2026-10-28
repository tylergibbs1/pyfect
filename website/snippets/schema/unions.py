from typing import assert_never

from pyfect import schema as S


class Card(S.TaggedClass):
    last4: str


class Invoice(S.TaggedClass):
    days: int


# A tagged union picks the member from the "_tag" key, so an error names one member.
Payment = S.TaggedUnion(Card, Invoice)
decode = S.decode_unknown_sync(Payment)

payment = decode({"_tag": "Invoice", "days": 30})
assert payment == Invoice(days=30)


# The decoded value is Card | Invoice: match on it, and pyright checks every case.
def describe(payment: Card | Invoice) -> str:
    match payment:
        case Card(last4=last4):
            return f"card ending {last4}"
        case Invoice(days=days):
            return f"invoice due in {days} days"
        case _:
            assert_never(payment)


print(describe(payment))

try:
    decode({"_tag": "Card", "last4": 1234})
except S.SchemaError as error:
    print(error.message)

# S.Union tries members in order, for unions without a tag.
IdOrName = S.Union(S.Int, S.String)
assert S.decode_unknown_sync(IdOrName)("ada") == "ada"
