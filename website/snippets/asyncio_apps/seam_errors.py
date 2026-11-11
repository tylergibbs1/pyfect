import asyncio
from dataclasses import dataclass

import pyfect as fx
from pyfect import layer
from pyfect.run import unwrap


@dataclass
class NotFound(fx.TaggedError):
    user_id: str


class HTTPException(Exception):
    """FastAPI's, here a stand-in: what the app's handlers raise."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(status_code, detail)
        self.status_code = status_code


class Users(fx.Tag[dict[str, str]]): ...


@fx.fn
def find_user(user_id: str):
    rows = yield from Users()
    if user_id not in rows:
        return (yield from NotFound(user_id))
    return rows[user_id]


# find_user(...) is an Effect[str, NotFound, Users]. run_async takes only an effect whose
# errors are all handled (Never), so each typed error is mapped where pyfect meets the app:
async def user_or_none(runtime: fx.ManagedRuntime[Users], user_id: str) -> str | None:
    # Either recover it into a value...
    found = find_user(user_id).pipe(fx.catch_tag(NotFound, lambda _: fx.succeed(None)))
    return await runtime.run_async(found)


async def get_user(runtime: fx.ManagedRuntime[Users], user_id: str) -> str:
    # ...or run for an Exit and turn the error into what the app raises.
    exit = await runtime.run_async_exit(find_user(user_id))
    match exit.find_error():
        case fx.Ok(value=NotFound() as error):
            raise HTTPException(404, f"no user {error.user_id}")
        case _:
            return unwrap(exit)  # the value; a defect or an interruption raises


async def main() -> None:
    async with fx.ManagedRuntime.make(layer.succeed(Users, {"1": "Ada"})) as runtime:
        print(await get_user(runtime, "1"), await user_or_none(runtime, "2"))
        try:
            await get_user(runtime, "2")
        except HTTPException as error:
            print(error.status_code, error)


asyncio.run(main())
