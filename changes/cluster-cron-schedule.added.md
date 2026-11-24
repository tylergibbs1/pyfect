- `cluster_cron.CronSchedule`: a cron job's effective schedule (`cron`,
  `calculate_next_run_from_previous` and `skip_if_older_than` as a `Duration`), provided to
  `execute` and annotated on the job's entity, so code inspecting registered entities can read
  it with `entity.annotations.get_option(cluster_cron.CronSchedule)` (Effect #10754).
