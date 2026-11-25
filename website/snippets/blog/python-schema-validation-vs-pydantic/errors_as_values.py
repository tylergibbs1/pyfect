from typing import Annotated, assert_type

import pyfect as fx
from pyfect import schema as S


class Signup(S.Class):
    email: str
    age: Annotated[int, S.is_between(minimum=13, maximum=130)]


decode = S.decode_unknown_result(Signup)

# No coercion: "29" is a string, and an int field doesn't take one.
# errors="all" reports every problem, not just the first.
result = decode({"email": 42, "age": "29"}, errors="all")
assert_type(result, fx.Result[Signup, S.SchemaError])
match result:
    case fx.Ok(signup):
        print(signup)
    case fx.Err(error):
        print(error.message)


# Inside an effect, decode_unknown_effect puts SchemaError in the error type.
@fx.fn
def register(body: object):
    signup = yield from S.decode_unknown_effect(Signup)(body)
    return f"welcome, {signup.email}"


assert_type(register({}), fx.Effect[str, S.SchemaError])


def handle(body: object) -> fx.Effect[str]:
    return register(body).pipe(
        fx.catch_tag(S.SchemaError, lambda e: fx.succeed(f"400: {e.message}"))
    )


print(fx.run_blocking(handle({"email": "ada@example.com", "age": 36})))
print(fx.run_blocking(handle({"email": "kid@example.com", "age": 9})))
