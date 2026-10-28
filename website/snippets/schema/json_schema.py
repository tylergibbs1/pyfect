import json

from pyfect import schema as S


class Signup(S.Class):
    username: str = S.field(S.String.check(S.is_min_length(3), S.is_max_length(20)))
    age: int = S.field(S.Int.check(S.is_greater_than_or_equal_to(13)))
    referrer: str | None = None


# The JSON Schema (draft 2020-12) of the JSON the schema reads and writes.
document = S.to_json_schema_document(Signup)
print(json.dumps({"schema": document.schema, "definitions": document.definitions}, indent=2))
