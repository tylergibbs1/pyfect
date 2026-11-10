from pyfect import schema as S
from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet

# Python's frozenset and dict treat True as 1, so FrozenSet and Map refuse to merge them.
Flags = S.to_codec_json(S.FrozenSet(S.Union(S.Int, S.Boolean)))
try:
    S.decode_unknown_sync(Flags)([1, True])
except S.SchemaError as error:
    print(error.message)

# HashSet and HashMap compare as Effect does, so 1 and True are two items.
HashFlags = S.to_codec_json(S.HashSet(S.Union(S.Int, S.Boolean)))
assert S.decode_unknown_sync(HashFlags)([1, True]) == HashSet[int | bool].make(1, True)

# In JSON, a map is a list of [key, value] pairs.
Scores = S.to_codec_json(S.HashMap(S.String, S.Int))
scores = S.decode_unknown_sync(Scores)([["ada", 3], ["alan", 2]])
assert scores == HashMap.make(("ada", 3), ("alan", 2))
print(S.encode_sync(Scores)(scores.set("grace", 5)))
