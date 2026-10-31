# Groups made with ``HttpApiGroup.make`` type their endpoints as ``Any``, so
# handler and client values here are untyped; tests/type_checks.py pins the types.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Ports of the ``original tests`` and ``HttpApiTest`` blocks of
``platform-node/test/HttpApi.test.ts``: one API of users, groups and a
top-level group, served by the live test server. Each test's docstring is
the Effect test title, prefixed by its ``describe`` blocks.

The OpenAPI fixture is Effect's vitest snapshot, converted to JSON
(tests/oracle/fixtures/http_api_openapi_fixture.json).
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyfect as fx
from pyfect import date_time, effect, layer, redacted
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.exit import Failure, Success
from pyfect.file_system import FileSystem
from pyfect.http import body as http_body
from pyfect.http import client as http_client
from pyfect.http import cookies, multipart, request, server_response
from pyfect.http.error import DecodeError, HttpClientError
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web
from pyfect.http_api import builder, client, get_group, openapi, security
from pyfect.http_api import endpoint as ep
from pyfect.http_api import schema as api_schema
from pyfect.http_api import test as api_test
from pyfect.http_api.api import AdditionalSchemas, HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware
from pyfect.redacted import Redacted
from pyfect.ref import Ref
from pyfect.schema import getter
from pyfect.schema.transformation import Transformation
from pyfect.testing import TestClock

from ._http_api import api_layer, run_served, struct

_EPOCH = datetime.fromtimestamp(0, UTC)


class UserError(S.TaggedError, annotations={"http_api_status": 400}):
    pass


class GroupError(S.TaggedError, annotations={"http_api_status": 418}):
    pass


class NoStatusError(S.TaggedError):
    pass


class User(S.Class, identifier="User", annotations={"description": "Some description for User"}):
    id: int = S.field(S.Int)
    name: str
    createdAt: datetime = S.field(S.DateTimeUtcFromString)


class Group(S.Class, identifier="Group"):
    id: int = S.field(S.Int)
    name: str


security_header = security.api_key(key="x-api-key")
security_query = security.api_key(key="api_key", in_="query")


class CurrentUser(Tag[User], key="CurrentUser"):
    pass


class Authorization(
    HttpApiMiddleware[CurrentUser],
    key="Authorization",
    security={"cookie": security.api_key(key="token", in_="cookie")},
):
    pass


_ID = struct({"id": S.FiniteFromString})
_NAMED = struct({"name": S.String})
_ID_AND_NAME = struct({"id": S.Finite, "name": S.String})
_UPLOADED = struct({"contentType": S.String, "length": S.Int})

GroupsApi = (
    HttpApiGroup.make("groups")
    .add(
        ep.get(
            "findById",
            "/:id",
            params=_ID,
            success=Group,
            error=api_schema.as_no_content(GroupError, decode=GroupError),
        ),
        ep.post(
            "create",
            "/",
            payload=(
                _NAMED,
                api_schema.as_form_url_encoded()(struct({"foo": S.String})),
                api_schema.as_multipart(_NAMED),
            ),
            success=Group,
        ),
        ep.post("handle", "/handle/:id", params=_ID, payload=_NAMED, success=_ID_AND_NAME),
        ep.post("handleRaw", "/handleraw/:id", params=_ID, payload=_NAMED, success=_ID_AND_NAME),
    )
    .prefix("/groups")
)

_PAGE = S.Finite.pipe(
    S.decode(Transformation(getter.with_default(Success(1.0)), getter.passthrough()))
)

UsersApi = (
    HttpApiGroup.make("users")
    .add(
        ep.get("findById", "/:id", params=struct({"id": S.Finite}), success=User, error=UserError),
        ep.post(
            "create",
            "/",
            payload=struct({"name": S.String, "uuid": S.String}, optional=["uuid"]),
            query=struct({"id": S.Finite}),
            success=User,
            error=(UserError, UserError),
        ),
        ep.get(
            "list",
            "/",
            headers=struct({"page": _PAGE}, optional=["page"]),
            query=struct(
                {"query": S.String.annotate(description="search query")}, optional=["query"]
            ),
            success=S.Array(User),
            error=NoStatusError,
        )
        .annotate(openapi.Deprecated, True)
        .annotate(openapi.Summary, "test summary")
        .annotate_merge(openapi.annotations(identifier="listUsers")),
        ep.post(
            "upload",
            "/upload/:0?",
            params=struct({"0": S.String}, optional=["0"]),
            payload=api_schema.as_multipart(struct({"file": multipart.SingleFileSchema})),
            success=_UPLOADED,
        ),
        ep.post(
            "uploadStream",
            "/uploadstream",
            payload=api_schema.as_multipart_stream(struct({"file": multipart.SingleFileSchema})),
            success=_UPLOADED,
        ),
    )
    .middleware(Authorization)
    .annotate_merge(openapi.annotations(title="Users API"))
)

TopLevelApi = HttpApiGroup.make("root", top_level=True).add(
    ep.get("healthz", "/healthz", success=api_schema.NoContent.annotate(description="Empty"))
)

AnotherApi = HttpApi.make("another").add(GroupsApi)


def _add_tag(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        **spec,
        "tags": [*spec.get("tags", []), {"name": "Tag from OpenApi.Transform annotation"}],
    }


Api = (
    HttpApi.make("api")
    .add_http_api(AnotherApi)
    .add(UsersApi.prefix("/users"))
    .add(TopLevelApi)
    .annotate_merge(
        openapi.annotations(title="API", summary="test api summary", transform=_add_tag)
    )
    .annotate(AdditionalSchemas, (_UPLOADED.annotate(identifier="ComponentsSchema"),))
)

Users = Api.groups["users"]
Groups = Api.groups["groups"]
Root = Api.groups["root"]


class UserRepo(Tag[Any], key="UserRepo"):
    pass


def _find_user(id: float) -> fx.Effect[User]:
    return date_time.now().map(lambda now: User(id=int(id), name="foo", createdAt=now))


UserRepoLive = layer.succeed(UserRepo, _find_user)


def _cookie(eff: Any, opts: Any) -> Any:
    token: Redacted[str] = opts.credential
    user = User(id=1, name=redacted.value(token), createdAt=datetime.now(UTC))
    return eff.pipe(fx.provide_service(CurrentUser, user))


AuthorizationLive = layer.succeed(Authorization, {"cookie": _cookie})


def _users_handlers(handlers: Any) -> Any:
    def build(services: tuple[Any, Any]) -> Any:
        fs, find = services

        def find_by_id(ctx: Any) -> Any:
            return CurrentUser() if ctx.params["id"] == -1 else find(ctx.params["id"])

        def create(ctx: Any) -> Any:
            if ctx.payload["name"] == "boom":
                return effect.fail(UserError())
            return date_time.now().map(
                lambda now: User(id=int(ctx.query["id"]), name=ctx.payload["name"], createdAt=now)
            )

        def list_users(ctx: Any) -> Any:
            page = ctx.headers["page"]
            if page == 0:
                return effect.fail(NoStatusError())
            return date_time.now_in_current_zone().map(
                lambda now: (User(id=1, name=f"page {page:g}", createdAt=now.astimezone(UTC)),)
            )

        def upload(ctx: Any) -> Any:
            file = ctx.payload["file"]
            return (
                fs.stat(file.path)
                .or_die()
                .map(lambda info: {"contentType": file.content_type, "length": info.size})
            )

        def upload_stream(ctx: Any) -> Any:
            def first(files: Any) -> Any:
                file, content = files[0]
                return {"contentType": file.content_type, "length": len(content)}

            files = ctx.payload.filter(multipart.is_file).map_effect(
                lambda file: file.content_effect.map(lambda content: (file, content))
            )
            return files.run_collect().or_die().map(first)

        e = Users.endpoints
        return (
            handlers.handle(e["findById"])(find_by_id)
            .handle(e["create"])(create)
            .handle(e["list"])(list_users)
            .handle(e["upload"])(upload)
            .handle(e["uploadStream"])(upload_stream)
        )

    return fx.all(FileSystem(), UserRepo()).map(build)


UsersLive = builder.group(Api, Users, _users_handlers).pipe(
    layer.provide(layer.merge(UserRepoLive, AuthorizationLive))
)


def _groups_handlers(handlers: Any) -> Any:
    def find_by_id(ctx: Any) -> Any:
        if ctx.params["id"] == 0:
            return effect.fail(GroupError())
        return effect.succeed(Group(id=1, name="foo"))

    def create(ctx: Any) -> Any:
        payload = ctx.payload
        return effect.succeed(
            Group(id=1, name=payload["foo"] if "foo" in payload else payload["name"])
        )

    def handle(ctx: Any) -> Any:
        return effect.succeed(
            server_response.json_unsafe({"id": ctx.params["id"], "name": ctx.payload["name"]})
        )

    def handle_raw(ctx: Any) -> Any:
        return ctx.request.json.or_die().map(
            lambda body: server_response.json_unsafe({"id": ctx.params["id"], "name": body["name"]})
        )

    e = Groups.endpoints
    return (
        handlers.handle(e["findById"])(find_by_id)
        .handle(e["create"])(create)
        .handle(e["handle"])(handle)
        .handle_raw(e["handleRaw"])(handle_raw)
    )


GroupsLive = builder.group(Api, Groups, _groups_handlers)
RootLive = builder.group(
    Api, Root, lambda h: h.handle(Root.endpoints["healthz"])(lambda _: effect.void)
)
App = api_layer(Api, layer.merge(GroupsLive, UsersLive, RootLive)).pipe(
    layer.provide(date_time.layer_current_zone_offset(0))
)


def _run(program: Any) -> Any:
    """``program`` against ``App``, at the epoch of a test clock (Effect's
    ``it.effect``)."""
    return run_served(App, effect.gen(program), TestClock.layer())


def _expected_user(name: str = "Joe", id: int = 123) -> User:
    return User(id=id, name=name, createdAt=_EPOCH)


def test_payload_is_decoded_encoded() -> None:
    """HttpApi / original tests / payload / is decoded / encoded"""

    def program() -> Any:
        http = yield from http_client.HttpClient()
        api_client = yield from client.make(Api)
        users_client = yield from client.group(Api, http_client=http, group=Users)
        create = yield from client.endpoint(
            Api, http_client=http, group=Users, endpoint=Users.endpoints["create"]
        )
        for method in (
            get_group(api_client, Users).method("create"),
            users_client.method("create"),
            create,
        ):
            user = yield from method(query={"id": 123}, payload={"name": "Joe"})
            assert user == _expected_user()

    _run(program)


def _hello_form() -> http_body.FormData:
    return http_body.FormData().append("file", http_body.File(b"hello", "hello.txt", "text/plain"))


def test_payload_multipart() -> None:
    """HttpApi / original tests / payload / multipart"""

    def program() -> Any:
        upload = get_group((yield from client.make(Api)), Users).method("upload")
        result = yield from upload(payload=_hello_form(), params={})
        assert result == {"contentType": "text/plain", "length": 5}

    _run(program)


def test_payload_multipart_stream() -> None:
    """HttpApi / original tests / payload / multipart stream"""

    def program() -> Any:
        upload = get_group((yield from client.make(Api)), Users).method("uploadStream")
        result = yield from upload(payload=_hello_form())
        assert result == {"contentType": "text/plain", "length": 5}

    _run(program)


def test_headers_should_accept_a_record_of_schemas() -> None:
    """HttpApi / original tests / headers / should accept a record of schemas"""
    group = HttpApiGroup.make("group").add(
        ep.get("get", "/:id", headers=struct({"id": S.FiniteFromString}), success=S.String)
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["get"])(
            lambda ctx: effect.succeed(f"User {ctx.headers['id']:g}")
        ),
    )

    def program() -> Any:
        get = get_group((yield from client.make(api)), group).method("get")
        assert (yield from get(headers={"id": 1})) == "User 1"

    run_served(api_layer(api, live), effect.gen(program))


def _list_page_one() -> Any:
    list_users = get_group((yield from client.make(Api)), Users).method("list")
    return (yield from list_users(headers={"page": 1}, query={}))


def test_headers_is_decoded_encoded() -> None:
    """HttpApi / original tests / headers / is decoded / encoded"""

    def program() -> Any:
        users = yield from _list_page_one()
        assert users[0] == _expected_user("page 1", 1)

    _run(program)


def test_errors_empty_errors_have_no_body() -> None:
    """HttpApi / original tests / errors / empty errors have no body"""

    def program() -> Any:
        response = yield from http_client.get("/groups/0")
        assert response.status == 418
        assert (yield from response.text) == ""

    _run(program)


def test_errors_empty_errors_decode() -> None:
    """HttpApi / original tests / errors / empty errors decode"""

    def program() -> Any:
        find = get_group((yield from client.make(Api)), Groups).method("findById")
        assert (yield from find(params={"id": 0}).flip()) == GroupError()

    _run(program)


def test_errors_default_to_500_status_code() -> None:
    """HttpApi / original tests / errors / default to 500 status code"""

    def program() -> Any:
        response = yield from http_client.execute(request.get("/users").set_headers({"page": "0"}))
        assert response.status == 500
        assert (yield from response.json) == {"_tag": "NoStatusError"}

    _run(program)


def test_errors_class_level_annotations() -> None:
    """HttpApi / original tests / errors / class level annotations"""

    def program() -> Any:
        sent = request.post("/users").set_url_params({"id": "0"}).body_json_unsafe({"name": "boom"})
        response = yield from http_client.execute(sent)
        assert response.status == 400

    _run(program)


def test_errors_bad_request() -> None:
    """HttpApi / original tests / errors / BadRequest"""

    def program() -> Any:
        upload = get_group((yield from client.make(Api)), Users).method("upload")
        error = yield from upload(params={}, payload=http_body.FormData()).flip()
        assert isinstance(error, HttpClientError)
        assert isinstance(error.reason, DecodeError)
        assert error.reason.response.status == 400

    _run(program)


def test_handler_level_context() -> None:
    """HttpApi / original tests / handler level context"""

    def program() -> Any:
        users = yield from _list_page_one()
        assert users[0].name == "page 1"
        assert users[0].createdAt == _EPOCH

    _run(program)


def test_custom_client_context() -> None:
    """HttpApi / original tests / custom client context"""
    tapped: list[bool] = []

    def tap(_request: Any) -> Any:
        tapped.append(True)
        return CurrentUser()

    def program() -> Any:
        http = (yield from http_client.HttpClient()).tap_request(tap)
        api_client = yield from client.make_with(Api, http_client=http)
        list_users = get_group(api_client, Users).method("list")
        users = yield from list_users(headers={"page": 1}, query={}).pipe(
            fx.provide_service(CurrentUser, _expected_user("foo", 1))
        )
        assert users[0].name == "page 1"
        assert tapped == [True]

    _run(program)


def test_security_middleware_sets_current_user() -> None:
    """HttpApi / original tests / security / security middleware sets current user"""

    def program() -> Any:
        jar = yield from Ref.make(cookies.EMPTY.set_unsafe("token", "foo"))
        http = (yield from http_client.HttpClient()).with_cookies_ref(jar)
        find = get_group((yield from client.make_with(Api, http_client=http)), Users).method(
            "findById"
        )
        user = yield from find(params={"id": -1})
        assert user.name == "foo"

    _run(program)


def _decode_security(scheme: Any, web: WebRequest, params: dict[str, str]) -> str:
    decoded = (
        builder.security_decode(scheme)
        .pipe(fx.provide_service(HttpServerRequest, request_from_web(web)))
        .pipe(fx.provide_service(ParsedSearchParams, params))
    )
    return redacted.value(fx.run_sync(decoded))


def test_security_api_key_header_security() -> None:
    """HttpApi / original tests / security / apiKey header security"""
    web = WebRequest("http://localhost:3000/", headers={"x-api-key": "foo"})
    assert _decode_security(security_header, web, {}) == "foo"


def test_security_api_key_query_security() -> None:
    """HttpApi / original tests / security / apiKey query security"""
    web = WebRequest("http://localhost:3000/")
    assert _decode_security(security_query, web, {"api_key": "foo"}) == "foo"


def test_client_response_mode_decoded_and_response() -> None:
    """HttpApi / original tests / client responseMode decoded-and-response"""

    def program() -> Any:
        list_users = get_group((yield from client.make(Api)), Users).method("list")
        users, response = yield from list_users.with_response(headers={"page": 1}, query={})
        assert users[0].name == "page 1"
        assert response.status == 200

    _run(program)


def test_client_response_mode_response_only_skips_decoding() -> None:
    """HttpApi / original tests / client responseMode response-only skips decoding"""
    group = HttpApiGroup.make("group").add(
        ep.get("bad", "/bad", success=struct({"value": S.Finite}))
    )
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle_raw(group.endpoints["bad"])(
            lambda _: effect.succeed(server_response.text("not-json"))
        ),
    )

    def program() -> Any:
        bad = get_group((yield from client.make(api)), group).method("bad")
        yield from bad().flip()
        response = yield from bad.response_only()
        assert response.status == 200
        assert (yield from response.text) == "not-json"

    run_served(api_layer(api, live), effect.gen(program))


def test_multiple_payload_types() -> None:
    """HttpApi / original tests / multiple payload types"""

    def program() -> Any:
        create = get_group((yield from client.make(Api)), Groups).method("create")
        group, response = yield from create.with_response(payload={"name": "Some group"})
        assert group == Group(id=1, name="Some group")
        assert response.status == 200
        form = http_body.FormData().append("name", "Some group")
        group, response = yield from create.with_response(payload=form)
        assert group == Group(id=1, name="Some group")
        assert response.status == 200
        group = yield from create(payload={"foo": "Some group"})
        assert group == Group(id=1, name="Some group")

    _run(program)


def test_handle_can_return_http_server_response() -> None:
    """HttpApi / original tests / .handle can return HttpServerResponse"""

    def program() -> Any:
        handle = get_group((yield from client.make(Api)), Groups).method("handle")
        response = yield from handle(params={"id": 1}, payload={"name": "Some group"})
        assert response == {"id": 1, "name": "Some group"}

    _run(program)


def test_handle_raw_can_manually_process_body() -> None:
    """HttpApi / original tests / .handleRaw can manually process body"""

    def program() -> Any:
        handle = get_group((yield from client.make(Api)), Groups).method("handleRaw")
        response = yield from handle(params={"id": 1}, payload={"name": "Some group"})
        assert response == {"id": 1, "name": "Some group"}

    _run(program)


_SAFE_INTEGER = {"maximum": 9007199254740991, "minimum": -9007199254740991}


def _python_wire(node: Any) -> Any:
    """Effect's document with pyfect's two wire differences: an ``int``
    has no safe-integer bounds, and an optional key (no ``undefined``)
    is the bare schema rather than ``anyOf`` it or null."""
    if isinstance(node, list):
        return [_python_wire(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {k: _python_wire(v) for k, v in node.items()}
    if out.get("type") == "integer" and all(out.get(k) == v for k, v in _SAFE_INTEGER.items()):
        out = {k: v for k, v in out.items() if k not in _SAFE_INTEGER}
    members = [m for m in out.get("anyOf", []) if m != {"type": "null"}]
    if "anyOf" in out and len(members) == 1:
        rest = {k: v for k, v in out.items() if k != "anyOf"}
        out = {**members[0], **rest}
    return out


def test_openapi_spec_fixture() -> None:
    """HttpApi / original tests / OpenAPI spec / fixture"""
    fixture = Path(__file__).parent / "fixtures" / "http_api_openapi_fixture.json"
    expected = _python_wire(json.loads(fixture.read_text()))
    # ``User.uuid`` is ``Schema.optional``: a schema class has no optional key.
    del expected["components"]["schemas"]["UserEncoded"]["properties"]["uuid"]
    assert openapi.from_api(Api) == expected


class RateLimitError(S.TaggedError):
    message: str


def test_error_from_plain_text() -> None:
    """HttpApi / original tests / error from plain text"""
    rate_limit = (
        S.String.pipe(
            S.decode_to(
                RateLimitError,
                Transformation(
                    # Between the string and the error's encoded form.
                    getter.transform(
                        lambda message: {"_tag": "RateLimitError", "message": message}
                    ),
                    getter.transform(lambda encoded: encoded["message"]),
                ),
            )
        )
        .pipe(api_schema.status("TooManyRequests"))
        .pipe(api_schema.as_text())
    )
    group = HttpApiGroup.make("group").add(ep.get("error", "/error", error=rate_limit))
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["error"])(
            lambda _: effect.fail(RateLimitError(message="Rate limit exceeded"))
        ),
    )

    def program() -> Any:
        error = get_group((yield from client.make(api)), group).method("error")
        assert (yield from error().flip()) == RateLimitError(message="Rate limit exceeded")

    run_served(api_layer(api, live), effect.gen(program))


def test_http_api_test_works() -> None:
    """HttpApi / HttpApiTest / works"""

    def unimplemented(_: object) -> fx.Effect[Any]:
        return effect.die(RuntimeError("unimplemented"))

    e = Groups.endpoints
    groups_live = builder.group(
        Api,
        Groups,
        lambda h: (
            h.handle(e["findById"])(lambda _: effect.succeed(Group(id=1, name="foo")))
            .handle(e["handle"])(unimplemented)
            .handle(e["create"])(unimplemented)
            .handle(e["handleRaw"])(unimplemented)
        ),
    )

    def program() -> Any:
        api_client = yield from api_test.groups(Api, [Groups])
        find = get_group(api_client, Groups).method("findById")
        assert (yield from find(params={"id": 0})) == Group(id=1, name="foo")

    exit_ = fx.run_sync(
        fx.scoped(effect.gen(program))
        .pipe(fx.provide(layer.merge(groups_live, AuthorizationLive)))
        .exit()
    )
    assert not isinstance(exit_, Failure), exit_
