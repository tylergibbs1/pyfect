from typing import Any

from pyfect import optic
from pyfect.result import Err, Ok
from pyfect.schema.issue import format_issue

type Json = dict[str, Any]

response: Json = {"data": {"items": [{"id": 1, "likes": 3}, {"id": 2, "likes": 5}]}}
empty: Json = {"data": {}}

# A path into a value. `at` fails with a schema issue when the key is missing.
items = optic.Id[Json]().at("data").at("items")
for page in [response, empty]:
    match items.get_result(page):
        case Ok(value=found):
            print("items:", len(found))
        case Err(error=issue):
            print("no items:", format_issue(issue))


# `for_each` focuses on every element; `modify_all` returns a changed copy and
# leaves the original as it was.
def like(n: int) -> int:
    return n + 1


likes = items.for_each(lambda item: item.key("likes"))
liked = likes.modify_all(like)(response)
print(likes.get_all(response), "->", likes.get_all(liked))
