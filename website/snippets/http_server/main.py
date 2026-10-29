import sys

import pyfect as fx
from pyfect import layer
from pyfect.http import router, server_response, uvicorn_server


@fx.fn
def add_routes(routes: router.HttpRouterService):
    yield from routes.add("GET", "/", server_response.text("hello"))


Routes = router.use(add_routes)

# `python main.py serve`: serve on port 8000 until interrupted (Ctrl-C), then
# give requests in flight up to 20 seconds to finish.
Main = router.serve(Routes).pipe(layer.provide(uvicorn_server.layer(port=8000)))

# `uvicorn main:app`: the same routes as an ASGI application, for any ASGI server.
app = router.to_asgi(Routes)

if sys.argv[1:] == ["serve"]:
    fx.run_main(Main.launch())
