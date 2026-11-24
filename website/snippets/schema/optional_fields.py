from pyfect import schema as S


class Rule(S.Class):
    id: str
    # None needs a schema that takes it: S.Undefined leaves the key out while it is None.
    min_count: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)
    # S.NullOr(S.Int) would write "min_count": null instead.


rule = S.decode_unknown_sync(Rule)({"id": "a"})
print(rule)
print(S.encode_sync(Rule)(rule))


try:

    class Broken(S.Class):
        min_count: int | None = S.field(S.Int, default=None)  # S.Int refuses None

except TypeError as error:  # where the class is defined
    print(error)
