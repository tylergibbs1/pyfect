import pyfect as fx
from pyfect.http import client, headers, request, response
from pyfect.http.client import HttpClient

PAGES = {"/items": ("a, b", "/items?page=2"), "/items?page=2": ("c", None)}


# A stand-in server that pages with Link headers, as GitHub's API does.
def handle(req: request.HttpClientRequest):
    path = req.url.removeprefix("https://api.example.com")
    body, next_page = PAGES[path]
    links = [] if next_page is None else [headers.Link(next_page, ("next",))]
    return fx.succeed(response.make(req, body, headers={"link": headers.format_link(links)}))


@fx.fn
def all_items():
    http = yield from HttpClient()
    url: str | None = "https://api.example.com/items"
    items: list[str] = []
    while url is not None:
        res = yield from http.get(url)
        items.extend((yield from res.text).split(", "))
        next_url = response.link(res, "next")  # resolved against the response URL
        url = None if next_url is None else next_url.href
    return items


print(fx.run_main(all_items().pipe(fx.provide(client.layer_test(handle)))))
print(headers.parse_link('</items?page=2>; rel="next last"'))
