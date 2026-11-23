- `HttpRouter`: an explicit route such as `GET /test` and a wildcard route `GET /test/*` can be
  registered together in either order. `/test` goes to the explicit route and `/test/anything`
  to the wildcard. Before, registering `/test` after `/test/*` died with "Method 'GET' already
  declared for route '/test'", and the other order did too. A wildcard registered alone still
  serves its bare prefix, and two explicit routes for the same path still fail (Effect #10768).
  `find_my_way.Router.on_fallback` registers a route that a later explicit one replaces.
