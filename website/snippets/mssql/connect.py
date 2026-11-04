import os

import pyfect as fx
from pyfect import redacted
from pyfect.sql import mssql
from pyfect.sql.error import UniqueViolation
from pyfect.sql.mssql import TYPES, Parameter, procedure

# MSSQL_SERVER=localhost MSSQL_PASSWORD=... MSSQL_DATABASE=app python connect.py
config = mssql.MssqlClientConfig(
    server=os.environ["MSSQL_SERVER"],
    port=int(os.environ.get("MSSQL_PORT", "1433")),
    database=os.environ["MSSQL_DATABASE"],
    username="sa",
    password=redacted.make(os.environ["MSSQL_PASSWORD"]),
    trust_server=True,
)

user_id = Parameter[int]("user_id", TYPES.Int)
email = Parameter[str]("email", TYPES.NVarChar)
email_of = procedure.make("email_of").param(user_id).output_param(email)


@fx.fn
def program():
    sql = yield from mssql.MssqlClient()
    yield from sql(
        "CREATE TABLE users (id INT IDENTITY PRIMARY KEY, "
        "email NVARCHAR(191) CONSTRAINT users_email UNIQUE)"
    )

    # returning(...) becomes SQL Server's OUTPUT clause.
    rows = yield from sql(
        "INSERT INTO users {}", sql.insert({"email": "ada@example.com"}).returning("*")
    )
    print(rows)

    # A failed statement's SqlError says why, read from SQL Server's error number.
    error = yield from sql("INSERT INTO users (email) VALUES ({})", "ada@example.com").flip()
    assert isinstance(error.reason, UniqueViolation)
    print(error.reason.constraint)

    # A stored procedure's output parameters come back typed by their Parameter.
    yield from sql(
        "CREATE PROCEDURE email_of @user_id INT, @email NVARCHAR(191) OUTPUT AS "
        "SELECT @email = email FROM users WHERE id = @user_id"
    )
    result = yield from sql.call(email_of.compile(user_id(1)))
    print(result.output[email])

    # A transaction rolls back when its effect fails.
    insert = sql("INSERT INTO users (email) VALUES ({})", "grace@example.com")
    yield from sql.with_transaction(insert.and_then(fx.fail("changed my mind"))).ignore()
    print((yield from sql("SELECT email FROM users ORDER BY id")))


fx.run_main(program().pipe(fx.provide(mssql.layer(config))))
