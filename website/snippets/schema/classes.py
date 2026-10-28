from pyfect import schema as S


class User(S.Class):
    id: int  # the annotation is the Type: S.Int is derived from it
    name: str = S.field(S.NonEmptyString)  # or give the field's schema
    tags: tuple[str, ...] = ()  # a default makes the key optional


# A schema class is a schema, and an ordinary class with a keyword __init__.
ada = User(id=1, name="Ada")
assert S.decode_unknown_sync(User)({"id": 1, "name": "Ada"}) == ada

# from_json_string reads and writes JSON text around any schema.
UserJson = S.from_json_string(User)
user = S.decode_unknown_sync(UserJson)('{"id": 2, "name": "Grace", "tags": ["navy"]}')
print(user)
print(S.encode_sync(UserJson)(user))
