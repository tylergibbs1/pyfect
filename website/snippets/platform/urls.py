import pyfect as fx
from pyfect.http import url

# Parsed and normalized as JavaScript's `new URL(text, base)` does.
api = fx.Url("../v2/users/?page=1#top", "HTTPS://API.Example.com:443/v1/")
print(api.href)
print(api.origin, api.pathname, api.search, api.hash)
print(fx.Url("https://例え.jp/a b").href)

# Immutable: each setter gives a new Url, as Effect's `Url.setX` does.
moved = url.set_url_params(url.set_port(api, 8443), {"page": 2, "q": "a b"})
print(moved)
print(dict(moved.search_params))

assert fx.Url.parse("http://[::1") is None
assert fx.Url("https://a.test/x") == fx.Url("HTTPS://A.TEST/./x")
