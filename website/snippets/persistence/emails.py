import pyfect as fx
from pyfect import layer, schedule
from pyfect import schema as S
from pyfect.persistence import persisted_queue
from pyfect.persistence.persisted_queue import Metadata


class Email(S.Class, identifier="Email"):
    to: str
    subject: str


def send(email: Email, meta: Metadata) -> fx.Effect[str, str]:
    print(f"attempt {meta.attempts}: {email.subject} to {email.to}")
    if meta.attempts == 1:
        return fx.fail("SMTP timeout")
    return fx.succeed(meta.id)


@fx.fn
def program():
    queue = yield from persisted_queue.make(
        name="emails", schema=Email, max_attempts=3, retry_schedule=schedule.spaced("50 millis")
    )
    welcome = Email(to="ada@example.com", subject="Welcome")
    yield from queue.offer(welcome, id="welcome-ada")
    yield from queue.offer(welcome, id="welcome-ada")  # the same id is stored once
    # A take whose handler fails fails too, and the email goes back on the queue.
    print("failed:", (yield from queue.take(send).flip()))
    # The next take gets it again once the retry delay has passed.
    print("sent:", (yield from queue.take(send)))


# Queues in memory; persisted_queue.layer_store_sql and layer_store_redis keep them
# across restarts and share them between processes.
Queues = persisted_queue.layer.pipe(layer.provide(persisted_queue.layer_store_memory))
fx.run_main(program().pipe(fx.provide(Queues)))
