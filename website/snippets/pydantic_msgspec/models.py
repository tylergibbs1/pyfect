from typing import Annotated

import msgspec
from pydantic import BaseModel

import pyfect as fx
from pyfect import msgspec as fx_msgspec
from pyfect import pydantic as fx_pydantic
from pyfect import schema as S


# A pydantic model as a pyfect schema: decoded with `model_validate`, encoded
# with `model_dump(mode="json")`, pydantic's errors as issues at their paths.
class Job(BaseModel):
    name: str
    schedule: str


class HarvestFile(BaseModel):
    timezone: str
    jobs: list[Job]


config = S.from_json_string(fx_pydantic.from_model(HarvestFile))
text = '{"timezone": "UTC", "jobs": [{"name": "countries", "schedule": "*/5 * * * *"}]}'
print(S.decode_unknown_sync(config)(text))
bad = S.decode_unknown_result(config)('{"jobs": [{"schedule": 5}]}', errors="all")
assert isinstance(bad, fx.Err)
print(bad.error.message)


# A msgspec struct as a pyfect schema, composed like any other.
class Change(msgspec.Struct):
    key: str
    op: str


log = S.from_json_string(S.Array(fx_msgspec.from_struct(Change)))
changes = S.decode_unknown_sync(log)('[{"key": "fr", "op": "add"}]')
assert changes == (Change(key="fr", op="add"),)
print(S.encode_sync(log)(changes))


# The other way: a pyfect schema as a pydantic field type.
class Order(BaseModel):
    total: Annotated[float, S.FiniteFromString]


print(Order.model_validate({"total": "9.5"}).total)
