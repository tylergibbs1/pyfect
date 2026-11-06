"""Writing schema values as compact binary frames."""

from typing import NotRequired, TypedDict

from pyfect import schema as S
from pyfect.encoding import schema_binary


class Person(TypedDict):
    name: str
    age: float
    nickname: NotRequired[str]


People = S.Struct(Person)

codec = schema_binary.to_codec(People)
ada: Person = {"name": "Ada", "age": 36}
frame = S.encode_sync(codec)(ada)
assert S.decode_sync(codec)(frame) == ada
print(len(frame), "bytes:", frame.hex())


class OlderPerson(TypedDict):
    name: str


# A reader skips the fields it does not know, and leaves missing optional ones
# out, so schemas can change on one side of a connection at a time.
older = schema_binary.to_codec(S.Struct(OlderPerson))
assert S.decode_sync(older)(frame) == {"name": "Ada"}

# Fingerprint mode has no field ids and adds an 8-byte hash of the layout:
# smaller for rows of many fields, and a peer whose layout differs fails.
exact = schema_binary.to_codec(People, fingerprint=True)
print("fingerprint:", len(S.encode_sync(exact)(ada)), "bytes")

# `encoder` and `parser` work across frames: a parser takes bytes as they come,
# split or joined, and a dictionary shortens strings a connection has seen.
writer = schema_binary.encoder(People, dictionary=True)
reader = schema_binary.parser(People, dictionary=True)
sizes: list[int] = []
for age in (36, 37, 38):
    data = writer.encode({"name": "Ada Lovelace", "age": age})
    sizes.append(len(data))
    assert reader.feed_sync(data) == [{"name": "Ada Lovelace", "age": age}]
print("dictionary:", sizes)
