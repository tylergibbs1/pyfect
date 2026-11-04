"""SQL drivers outside ``effect/sql``: MySQL (``@effect/sql-mysql2``), SQL
Server (``@effect/sql-mssql``), libSQL (``@effect/sql-libsql``), ClickHouse
(``@effect/sql-clickhouse``), Cloudflare D1 (``@effect/sql-d1``), PostgreSQL's
client and migrator (``@effect/sql-pg``) and the Node SQLite client
(``@effect/sql-sqlite-node``)."""

from api_coverage import Cluster, Module

ISINSTANCE = "`TypeId` symbols and `is*` guards"

D1 = Module(
    "D1Client",
    "sql/d1/src/D1Client.ts",
    ("pyfect.sql.d1",),
    pythonic={"TypeId": (ISINSTANCE, "`isinstance(client, D1ClientService)`")},
)

SQLITE_NODE = Module(
    "SqliteClient (sqlite-node)",
    "sql/sqlite-node/src/SqliteClient.ts",
    ("pyfect.sql.sqlite",),
    pythonic={"TypeId": (ISINSTANCE, "`isinstance(client, SqliteClientService)`")},
)

SQLITE_NODE_MIGRATOR = Module(
    "SqliteMigrator (sqlite-node)",
    "sql/sqlite-node/src/SqliteMigrator.ts",
    ("pyfect.sql.sqlite.migrator",),
)


def _driver(name: str, source: str, *spaces: str) -> Module:
    return Module(name, source, spaces, pythonic={"TypeId": (ISINSTANCE, "`isinstance`")})


MYSQL = _driver("MysqlClient", "sql/mysql2/src/MysqlClient.ts", "pyfect.sql.mysql")
MYSQL_MIGRATOR = Module(
    "MysqlMigrator", "sql/mysql2/src/MysqlMigrator.ts", ("pyfect.sql.mysql.migrator",)
)
MSSQL = _driver("MssqlClient", "sql/mssql/src/MssqlClient.ts", "pyfect.sql.mssql")
MSSQL_MIGRATOR = Module(
    "MssqlMigrator", "sql/mssql/src/MssqlMigrator.ts", ("pyfect.sql.mssql.migrator",)
)
MSSQL_PARAMETER = Module(
    "Parameter (mssql)",
    "sql/mssql/src/Parameter.ts",
    ("pyfect.sql.mssql.parameter",),
    renamed={"make": "pyfect.sql.mssql.parameter.Parameter"},
    pythonic={"TypeId": (ISINSTANCE, "`isinstance(value, Parameter)`")},
)
MSSQL_PROCEDURE = Module(
    "Procedure (mssql)",
    "sql/mssql/src/Procedure.ts",
    ("pyfect.sql.mssql.procedure", "pyfect.sql.mssql.procedure:Procedure"),
    pythonic={"TypeId": (ISINSTANCE, "`isinstance(value, Procedure)`")},
)
LIBSQL = _driver("LibsqlClient", "sql/libsql/src/LibsqlClient.ts", "pyfect.sql.libsql")
LIBSQL_MIGRATOR = Module(
    "LibsqlMigrator", "sql/libsql/src/LibsqlMigrator.ts", ("pyfect.sql.libsql.migrator",)
)
CLICKHOUSE = _driver(
    "ClickhouseClient", "sql/clickhouse/src/ClickhouseClient.ts", "pyfect.sql.clickhouse"
)
CLICKHOUSE_MIGRATOR = Module(
    "ClickhouseMigrator",
    "sql/clickhouse/src/ClickhouseMigrator.ts",
    ("pyfect.sql.clickhouse.migrator",),
)
PG = _driver("PgClient", "sql/pg/src/PgClient.ts", "pyfect.sql.pg")
PG_MIGRATOR = Module("PgMigrator", "sql/pg/src/PgMigrator.ts", ("pyfect.sql.pg.migrator",))
PG_POOL = _driver("PgPool", "sql/pg/src/PgPool.ts", "pyfect.sql.pg.pool")
PG_CONNECTION = _driver("PgConnection", "sql/pg/src/PgConnection.ts", "pyfect.sql.pg.connection")

CLUSTER = Cluster(
    "sql-drivers",
    "SQL drivers (MySQL, SQL Server, libSQL, ClickHouse, D1, PostgreSQL, SQLite on Node)",
    (
        MYSQL,
        MYSQL_MIGRATOR,
        MSSQL,
        MSSQL_MIGRATOR,
        MSSQL_PARAMETER,
        MSSQL_PROCEDURE,
        LIBSQL,
        LIBSQL_MIGRATOR,
        CLICKHOUSE,
        CLICKHOUSE_MIGRATOR,
        D1,
        PG,
        PG_MIGRATOR,
        PG_POOL,
        PG_CONNECTION,
        SQLITE_NODE,
        SQLITE_NODE_MIGRATOR,
    ),
)
