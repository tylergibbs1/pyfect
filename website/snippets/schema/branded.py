import re
from typing import NewType, TypedDict, TypeIs, assert_type

from pyfect import schema as S
from pyfect.brand import Brand

# Two strings that must not be mixed up: pyright tells them apart, at run time they are str.
TenantSlug = NewType("TenantSlug", str)
AccountCode = NewType("AccountCode", str)

_slug = re.compile(r"[a-z][a-z0-9]{2,29}")


def is_slug(value: str) -> TypeIs[TenantSlug]:
    return _slug.fullmatch(value) is not None


# S.refine narrows the type to what the guard accepts.
Slug = S.String.pipe(S.refine(is_slug, expected="a tenant slug"))

# S.from_brand runs a Brand's checks, the same ones Brand's constructors run.
to_code = Brand[str, AccountCode].check(S.is_min_length(1), S.is_max_length(40))
Code = S.String.pipe(S.from_brand(to_code))


class Line(TypedDict):
    account: AccountCode  # a field of a branded type takes the branded schema
    amount: int


LineSchema = S.Struct(Line, account=Code)

slug = S.decode_unknown_sync(Slug)("acme")
assert_type(slug, TenantSlug)
print(slug)
print(S.decode_unknown_result(Slug)("Acme Inc"))

line = S.decode_unknown_sync(LineSchema)({"account": "cash", "amount": 100})
assert_type(line["account"], AccountCode)
print(line)
print(to_code("bank"))
