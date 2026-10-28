"""Fetch a user with a timeout and three retries, in plain asyncio."""

import asyncio


class UserNotFound(Exception):
    pass


async def fetch_user(user_id: str) -> str:
    await asyncio.sleep(0.01)
    if user_id != "1":
        raise UserNotFound(user_id)
    return "Ada"


async def greet(user_id: str) -> str:
    for attempt in range(3):
        try:
            name = await asyncio.wait_for(fetch_user(user_id), timeout=1)
            return f"Hello, {name}!"
        except TimeoutError:
            await asyncio.sleep(0.1 * 2**attempt)
        except UserNotFound:
            return "Who?"
    raise TimeoutError


# Nothing in greet's signature says it can raise TimeoutError, and nothing
# reminds the caller to handle it.
assert asyncio.run(greet("1")) == "Hello, Ada!"
