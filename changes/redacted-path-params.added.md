- `redacted_params` on `router.route`, `router.add` and `HttpRouterService.add`, and `params` on
  `http_api.RedactedNames`: the server span and the `middleware.logger` entry record the matched
  path with those params' values replaced by `REDACTED` (Effect #10790). A 5xx span error's
  request URL also hides the endpoint's redacted query names now.
