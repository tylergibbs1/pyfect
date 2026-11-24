- `observability.otlp_metrics` exports a metric without a declared unit with an empty unit
  instead of `"1"`, as in Effect 4.1.4 (Effect-TS/effect#10385). Prometheus-compatible
  backends stop adding `_ratio` to such gauge names (`app_build_info_ratio` becomes
  `app_build_info`); give the metric `attributes={"unit": "1"}` to keep the old name.
