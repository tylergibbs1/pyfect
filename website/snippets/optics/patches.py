from pyfect import json_patch
from pyfect.json_patch import JsonValue

before: JsonValue = {"name": "pyfect", "tags": ["effect"], "stars": 10}
after: JsonValue = {"name": "pyfect", "tags": ["effect", "python"], "stars": 12}

# The operations turning one JSON value into another: add, remove, replace.
patch = json_patch.get(before, after)
for op in patch:
    print(op)

# `apply` builds a new value; `before` is unchanged.
assert json_patch.apply(patch, before) == after
assert json_patch.get(after, after) == []
