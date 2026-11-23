- An RPC socket client's pings keep their rhythm across reconnects, as in Effect. Each
  reconnect restarted the ping interval, so a client's silence verdicts shifted by however long
  its reconnects took. Effect's pinger keeps ticking from when it started, whatever the socket
  does. The interval still restarts at the first open, so a request that times out at twice the
  interval still finds the connection's error on its retry.
