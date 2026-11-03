from pyfect import schema as S

# A record's keys are selected by the key schema: a key that fails it is not an entry.
Tasks = S.Record(S.String.check(S.is_pattern(r"^[a-z]+$")), S.Number)
config = {"build": 1, "a b": 2}

# By default an unmatched key is an excess property, and excess properties are dropped.
assert S.decode_unknown_sync(Tasks)(config) == {"build": 1}

# on_excess_property="error" rejects it instead, which is what a config file wants.
try:
    S.decode_unknown_sync(Tasks)(config, on_excess_property="error")
except S.SchemaError as error:
    print(error.message)
