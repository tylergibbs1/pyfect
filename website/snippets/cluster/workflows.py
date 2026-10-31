from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.cluster import cluster_workflow_engine, test_runner
from pyfect.workflow import activity, durable_deferred, workflow


class Signup(TypedDict):
    email: str


SignUp = workflow.make(
    "SignUp",
    payload=S.Struct(Signup),
    success=S.String,
    idempotency_key=lambda signup: signup["email"],
)
Confirmed = durable_deferred.make("confirmed", success=S.Boolean)


@fx.fn
def sign_up(signup: Signup, _execution_id: str):
    yield from activity.make(
        name="send-link", execute=fx.sync(lambda: print("link sent to", signup["email"]))
    )
    confirmed = yield from Confirmed.wait()
    return "active" if confirmed else "closed"


# The same workflow, now run by the cluster: each execution is an entity, its
# activities and deferred results are persisted messages, and it moves with its shard.
cluster = (
    SignUp.to_layer(sign_up)
    .pipe(fx.layer.provide_merge(cluster_workflow_engine.layer))
    .pipe(fx.layer.provide_merge(test_runner.layer))
)


@fx.gen
def program():
    signup: Signup = {"email": "ada@example.com"}
    execution_id = yield from SignUp.execute(signup, discard=True)
    token = Confirmed.token_from_execution_id(workflow=SignUp, execution_id=execution_id)
    yield from Confirmed.succeed(token=token, value=True)
    # Executing again with the same idempotency key joins the first execution.
    print("status:", (yield from SignUp.execute(signup)))


fx.run_main(program.pipe(fx.provide(cluster)))
