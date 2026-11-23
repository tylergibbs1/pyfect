- `tool.ProviderToolConstructor`, the type of a provider-defined tool's constructor:
  `failure_mode` is typed, and `failure_mode="return"` gives a tool whose handler raises
  nothing to its caller. `ProviderDefined`'s `set_failure`, `set_success`, `set_parameters`
  and `add_dependency` return a `ProviderDefined`.
