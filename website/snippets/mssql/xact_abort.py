import os

import pyfect as fx
from pyfect import redacted
from pyfect.sql import mssql
from pyfect.sql.error import SqlError
from pyfect.sql.mssql.error import error_number

config = mssql.MssqlClientConfig(
    server=os.environ["MSSQL_SERVER"],
    port=int(os.environ.get("MSSQL_PORT", "1433")),
    database=os.environ["MSSQL_DATABASE"],
    username="sa",
    password=redacted.make(os.environ["MSSQL_PASSWORD"]),
    trust_server=True,
)


def thrown(cause: fx.Cause[SqlError]) -> int | None:
    """The error number a procedure threw, whether the effect failed or died with it."""
    error = cause.squash()
    return error_number(error.reason.cause) if isinstance(error, SqlError) else None


@fx.fn
def program():
    sql = yield from mssql.MssqlClient()
    yield from sql("CREATE TABLE entries (id INT IDENTITY PRIMARY KEY, amount INT)")
    yield from sql(
        "CREATE PROCEDURE post_entry @amount INT AS BEGIN SET XACT_ABORT ON;"
        " IF @amount > 100 THROW 50001, 'overdrawn', 1;"
        " INSERT INTO entries (amount) VALUES (@amount); END"
    )
    post = sql("EXEC post_entry @amount = {}", 500)

    # On its own, the THROW is a failure, and its number is on the reason's cause.
    error = yield from post.flip()
    print(type(error.reason).__name__, error_number(error.reason.cause))

    # In a transaction, XACT_ABORT has rolled it back before the client hears of the THROW,
    # so with_transaction's ROLLBACK fails (3903) and the transaction dies with both.
    failed = yield from sql.with_transaction(post).exit()
    assert isinstance(failed, fx.Failure)
    print([type(reason).__name__ for reason in failed.cause.reasons])
    defects = [d for d in failed.cause.defects if isinstance(d, SqlError)]
    print([error_number(defect.reason.cause) for defect in defects])

    # catch_tag(SqlError) can't see a defect; catch_cause can, and so finds the number.
    number = yield from sql.with_transaction(post).catch_cause(lambda c: fx.succeed(thrown(c)))
    print(number)


fx.run_main(program().pipe(fx.provide(mssql.layer(config))))
