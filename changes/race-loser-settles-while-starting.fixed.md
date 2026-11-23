- `race`, `race_first`, `race_all` and `race_all_first` interrupt a racer that settles the race
  during its own first step. Such a racer used to run on after the race was decided (code after
  completing the `Deferred` the winner waited on ran, and the racer ended with its own value),
  and a racer whose fiber settled the race as it was built (a `FiberRuntimeMetrics` hook) still
  ran. Each racer is now registered with the race before it runs.
