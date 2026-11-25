from pydantic import BaseModel

from pyfect import pydantic as fx_pydantic
from pyfect import schema as S


# A model you already have, validated by pydantic.
class Address(BaseModel):
    city: str
    postcode: str


# from_model makes it a pyfect schema, so it composes with codecs and classes.
class Customer(S.Class):
    name: str = S.field(S.Trim)
    address: Address = S.field(fx_pydantic.from_model(Address))


CustomerJson = S.from_json_string(Customer)
customer = S.decode_unknown_sync(CustomerJson)(
    '{"name": " Ada ", "address": {"city": "London", "postcode": "N1"}}'
)
print(customer.address)
print(S.encode_sync(CustomerJson)(customer))
