- `ClickhouseClientConfig(disable_initial_ping=True)` skips the `/ping` that `clickhouse.make`
  sends at startup, so the client builds without a server and a statement fails when it can't
  connect. The default still pings (Effect-TS/effect#10782).
