import os

import pyfect as fx
from pyfect import redacted
from pyfect.sql import mysql
from pyfect.sql.error import UniqueViolation

# DATABASE_URL=mysql://user:password@localhost:3306/app python connect.py
config = mysql.MysqlClientConfig(
    url=redacted.make(os.environ["DATABASE_URL"]),
    max_connections=5,
)


@fx.fn
def program():
    sql = yield from mysql.MysqlClient()
    yield from sql(
        "CREATE TABLE users (id INT AUTO_INCREMENT PRIMARY KEY, email VARCHAR(191) UNIQUE)"
    )

    # A statement that changes rows gives no rows; .raw gives mysql2's
    # ResultSetHeader with the count and the generated id.
    header = yield from sql("INSERT INTO users (email) VALUES ({})", "ada@example.com").raw
    print(header)

    # A failed statement's SqlError says why, read from MySQL's error number.
    error = yield from sql("INSERT INTO users (email) VALUES ({})", "ada@example.com").flip()
    assert isinstance(error.reason, UniqueViolation)
    print(error.reason.constraint)

    # A transaction rolls back when its effect fails.
    insert = sql("INSERT INTO users (email) VALUES ({})", "grace@example.com")
    yield from sql.with_transaction(insert.and_then(fx.fail("changed my mind"))).ignore()
    print((yield from sql("SELECT email FROM users ORDER BY id")))


fx.run_main(program().pipe(fx.provide(mysql.layer(config))))
