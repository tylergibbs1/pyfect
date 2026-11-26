class UserNotFound(Exception):
    pass


USERS = {"1": "Ada"}


def load_user(user_id: str) -> str:
    if user_id not in USERS:
        raise UserNotFound(user_id)
    return USERS[user_id]


def greeting(user_id: str) -> str:
    # pyright accepts this: nothing in load_user's type says it can raise.
    return f"Hello, {load_user(user_id)}"


print(greeting("1"))
try:
    greeting("2")
except UserNotFound as error:
    print(f"crashed: {error!r}")
