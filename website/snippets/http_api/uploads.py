from pathlib import Path
from typing import TypedDict

import pyfect as fx
from pyfect import layer, stream
from pyfect import schema as S
from pyfect.http import body, multipart, router, uvicorn_server
from pyfect.http_api import (
    HttpApi,
    HttpApiGroup,
    HttpApiRequest,
    builder,
    client,
    endpoint,
    get_group,
)
from pyfect.http_api import schema as api_schema


class Upload(TypedDict):
    title: str
    file: multipart.PersistedFile


class Stored(TypedDict):
    title: str
    name: str
    size: int


class Progress(TypedDict):
    done: int
    total: int


class Files(HttpApiGroup, identifier="files"):
    # A multipart/form-data body: the server writes file parts to disk before the handler
    # runs, and SingleFileSchema takes exactly one file for the field.
    upload = endpoint.post(
        "upload",
        "/files",
        payload=api_schema.as_multipart(
            S.Struct(Upload, file=multipart.SingleFileSchema), max_file_size=1_000_000
        ),
        success=S.Struct(Stored),
    )
    # A text/event-stream response: each element of the stream is one event's data.
    progress = endpoint.get(
        "progress", "/progress", success=api_schema.StreamSse(data=S.Struct(Progress))
    )


api = HttpApi.make("example").add(Files)


@fx.fn
def upload(request: HttpApiRequest[None, None, Upload, None]):
    file = request.payload["file"]
    content = yield from fx.blocking(lambda: Path(file.path).read_bytes())
    return Stored(title=request.payload["title"], name=file.name, size=len(content))


def progress(_request: HttpApiRequest[None, None, None, None]):
    return fx.succeed(stream.make(*(Progress(done=i, total=3) for i in range(1, 4))))


FilesLive = builder.group(
    api,
    Files,
    lambda handlers: handlers.handle(Files.upload)(upload).handle(Files.progress)(progress),
)
ApiLive = builder.layer(api).pipe(layer.provide(FilesLive))


@fx.fn
def program():
    files = get_group((yield from client.make(api)), Files)
    # The client sends a multipart payload as FormData.
    form = (
        body.FormData()
        .append("title", "Q3 numbers")
        .append("file", body.File(b"a,b\n1,2\n", "q3.csv", "text/csv"))
    )
    print((yield from files.upload(payload=form)))
    # An SSE endpoint's client method gives a stream of the decoded events.
    events = yield from files.progress()
    yield from events.run_for_each(lambda p: fx.sync(lambda: print("progress", p)))


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(program().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
