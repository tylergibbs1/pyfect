- `Tool`, `ProviderDefined` and `Dynamic` carry their `failure_mode` as a seventh type
  parameter (`Literal["error"]` or `Literal["return"]`; it defaults to `FailureMode`, so a
  six-argument `Tool[...]` annotation still means a tool of either mode), and `set_failure`
  keeps it, as Effect's `Tool.setFailure` does. `set_failure` gives back the same kind of
  tool (a `Dynamic` stays `Dynamic`; so do its `set_success` and `add_dependency`) whose
  handler error is the new failure in `"error"` mode and `Never` in `"return"` mode; it was
  `Any`, so code that mishandled that error type-checked and now does not. What to do
  instead: handle or declare the failure the toolkit now reports for an `"error"`-mode tool,
  and in an exact annotation of a tool's type (`assert_type`, a variable's declared type)
  add the mode, as in `Tool[N, P, S, F, F, R, Literal["error"]]`. `mcp_client.toolkit` gives
  `transform_tool` the new `mcp_client.ModedRemoteTool[S, HE, M]`, a `RemoteTool` that keeps
  its mode, so a `transform_tool` that calls `set_failure` on a `"return"`-mode tool
  annotates its parameter `ModedRemoteTool[str, Never, Literal["return"]]` (one annotated
  `RemoteTool` is still accepted). A `failure_mode` argument typed `Any` now leaves the
  tool's type unknown; type it `tool.FailureMode`.
