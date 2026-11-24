- OTLP and OpenTelemetry spans that succeed, or fail without a reportable error, keep the
  status Unset instead of being set to Ok, as in Effect 4.1.4 (Effect-TS/effect#10440);
  `otel.tracer` no longer overwrites a status the application set on the span in those cases.
  Queries and dashboards that filter on Ok should also match Unset.
