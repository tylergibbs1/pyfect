- `SqlClient.reserve`: a reserved connection held in a scope that outlives the client (or its
  layer) no longer deadlocks the client's shutdown on PostgreSQL, MySQL and SQL Server. The pool
  waited for the connection to come back, which happened only when that scope closed, after the
  client's. Closing the client now closes the connection, and a later statement on it fails with
  the driver's `SqlError`.
