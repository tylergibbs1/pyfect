from typing import TypedDict

import pyfect as fx
from pyfect import schema as S


class Line(TypedDict):
    sku: str
    quantity: int


# The TypedDict is the Type; keyword arguments refine fields beyond their annotation.
LineSchema = S.Struct(Line, quantity=S.Int.check(S.is_between(minimum=1, maximum=99)))

decode = S.decode_unknown_sync(LineSchema)
line = decode({"sku": "apple", "quantity": 2})
assert line == {"sku": "apple", "quantity": 2}

# A bad payload raises SchemaError, whose message says what was wrong and where.
try:
    decode({"sku": "apple", "quantity": 0})
except S.SchemaError as error:
    print(error.message)

# The _result variants return the failure instead of raising; errors="all" reports
# every problem, not just the first.
result = S.decode_unknown_result(LineSchema)({"sku": 1}, errors="all")
assert isinstance(result, fx.Err)
print(result.error.message)

# Encoding runs the schema backwards, to the wire form.
assert S.encode_sync(LineSchema)(line) == {"sku": "apple", "quantity": 2}
