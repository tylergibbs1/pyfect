from typing import TypedDict

from pyfect import schema as S


class Signup(TypedDict):
    username: str
    age: int


SignupSchema = S.Struct(Signup, username=S.NonEmptyString)

# The adapter is still the schema, plus a Standard Schema `__standard__`.
standard = S.to_standard_json_schema_v1(S.to_standard_schema_v1(SignupSchema))
props = standard.__standard__
print(props.vendor, props.version)

assert props.validate is not None
print(props.validate({"username": "ada", "age": 36}))
print(props.validate({"username": "", "age": "36"}))

assert props.json_schema is not None
print(props.json_schema.input(target="draft-07"))
