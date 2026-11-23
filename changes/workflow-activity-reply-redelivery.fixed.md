- Cluster workflows: an activity's result reaches its workflow when the activity's reply is
  redelivered to the same runner. That happens when the runner's shard-ownership check fails
  once while the reply is being saved. Before, the redelivered request found no registration
  and answered `Suspended`, so the workflow waited forever. A redelivered activity now returns
  the result it already produced, without running again, unless it runs `WithTransaction`, in
  which case its transaction rolled back and it runs again. Two attempts of the same activity
  running at once (an `activity.CurrentAttempt` given to each) also get their own results
  instead of hanging. A runner that gives up a request it no longer owns releases its claim
  only after the request's fiber has exited, so the storage poll can't hand the request back
  while the runner would still drop it (Effect #10791).
