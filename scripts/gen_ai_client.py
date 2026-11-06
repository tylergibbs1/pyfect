"""The client part of ``gen_ai_schemas.py``: Effect's generated client (the
``make`` of ``Generated.ts`` and its ``<Name>Client`` interface) as a
Python class with a method per operation, over
``pyfect.ai._generated_client``.

The implementation gives each operation's method, path, query and header
parameters, body and response handling; the interface gives the types of
its options and its documentation. Both are read with patterns for the
exact shapes Effect's generators emit (the ``Generated.ts`` of OpenRouter
and OpenAI come from different ones: OpenAI's percent-encodes and checks path
parameters, has binary 2xx bodies and sends streams through the transform):
an operation of any other shape is an error naming it, so an Effect update
fails loudly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ClientShapeError(Exception):
    """The client has a shape this generator does not know."""


@dataclass(frozen=True)
class ClientTarget:
    title: str
    package: str
    client_title: str
    """The API's name in Effect's client (``OpenAi`` where the title is
    ``OpenAI``)."""

    @property
    def client_name(self) -> str:
        return f"{self.client_title}Client"


@dataclass(frozen=True)
class Signature:
    """An operation's options, from the interface."""

    name: str
    doc: str
    path_args: tuple[str, ...]
    params: str | None
    params_required: bool
    payload: str | None


@dataclass
class Operation:
    """An operation, from the implementation."""

    name: str
    method: str
    path: str
    path_args: tuple[str, ...]
    encoded_path: bool = False
    """``path`` is a template of ``{}`` over ``path_args``, encoded and
    checked when the request is made (Effect's ``__makePathRequest``)."""
    url_params: list[str] = field(default_factory=list[str])
    headers: list[str] = field(default_factory=list[str])
    body: str | None = None
    kind: str = "json"
    success: str | None = None
    status_success: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    binary_success: bool = False
    errors: list[tuple[int, str, str]] = field(default_factory=list[tuple[int, str, str]])
    void: list[int] = field(default_factory=list[int])
    stream_schema: str | None = None


def snake(name: str) -> str:
    """``exchangeAuthCodeForAPIKey`` as ``exchange_auth_code_for_api_key``."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


# --- the implementation -----------------------------------------------------------------

_METHOD = r"HttpClientRequest\.(?P<method>get|post|put|patch|delete)"
_HEAD = re.compile(r'^"(?P<name>\w+)": \((?P<args>[\w, ]*)\) => ')
_PLAIN_REQUEST = re.compile(
    rf"^{_METHOD}\((?:`(?P<template>[^`]*)`|\"(?P<literal>[^\"]*)\")\)\.pipe\("
)
_CHECKED_REQUEST = re.compile(
    rf"^(?P<stream>Stream\.unwrap\()?__makePathRequest\({_METHOD}, "
    r"\[(?P<values>[\w, ]*)\], \(\) => (?P<path>[^)]*(?:\([^)]*\)[^)]*)*)\)\.pipe\("
    r"Effect\.(?P<lift>flatMap|map)\(\(request\) => request\.pipe\("
)
_ENCODED_PARAMETER = re.compile(r"^__encodePathParam\((\w+)\)$")
_PATH_LITERAL = re.compile(r'^"([^"{}]*)"$')
_URL_PARAMS = re.compile(r"^HttpClientRequest\.setUrlParams\(\{ (?P<entries>[^}]*) \}\), ")
_HEADERS = re.compile(r"^HttpClientRequest\.setHeaders\(\{ (?P<entries>[^}]*) \}\), ")
_BODY = re.compile(
    r"^HttpClientRequest\.(?P<body>bodyJsonUnsafe\(options\.payload\)"
    r"|bodyFormData(?:Record)?\(options\.payload as any\)), "
)
_JSON = re.compile(
    r"^withResponse\(options\??\.config\)\(HttpClientResponse\.matchStatus\(\{ "
    r"(?P<cases>.*?)orElse: unexpectedStatus \}\)\)\)$"
)
_SSE = re.compile(r"^sseRequest\((?P<schema>\w+)\)\)$")
_BINARY = re.compile(r"^binaryRequest\)$")
_PARAM = r"options\??\.params(?:\?\.)?\[\"(?P<inner>[^\"]+)\"\]"
_URL_ENTRY = re.compile(rf'^"(?P<key>[^"]+)": {_PARAM} as any$')
_HEADER_ENTRY = re.compile(rf'^"(?P<key>[^"]+)": {_PARAM} \?\? undefined$')
_SUCCESS_CASE = re.compile(r'^"2xx": decodeSuccess\((?P<schema>\w+)\)$')
_STATUS_SUCCESS_CASE = re.compile(r'^"(?P<status>\d{3})": decodeSuccess\((?P<schema>\w+)\)$')
_BINARY_CASE = '"2xx": decodeBinary'
_VOID_CASE = re.compile(r'^"(?P<status>\d{3})": \(\) => Effect\.void$')
_ERROR_CASE = re.compile(r'^"(?P<status>\d{3})": decodeError\("(?P<tag>\w+)", (?P<schema>\w+)\)$')


def _entries(text: str, pattern: re.Pattern[str], where: str) -> list[str]:
    keys: list[str] = []
    for entry in text.split(", "):
        match = pattern.match(entry)
        if match is None or match.group("key") != match.group("inner"):
            raise ClientShapeError(f"unknown {where} entry {entry!r}")
        keys.append(match.group("key"))
    return keys


def _status_cases(operation: Operation, cases: str) -> None:
    for case in re.split(r", (?=\")", cases) if cases else []:
        if success := _SUCCESS_CASE.match(case):
            operation.success = success.group("schema")
        elif status_success := _STATUS_SUCCESS_CASE.match(case):
            operation.status_success.append(
                (int(status_success.group("status")), status_success.group("schema"))
            )
        elif case == _BINARY_CASE:
            operation.binary_success = True
        elif void := _VOID_CASE.match(case):
            operation.void.append(int(void.group("status")))
        elif error := _ERROR_CASE.match(case):
            operation.errors.append(
                (int(error.group("status")), error.group("tag"), error.group("schema"))
            )
        else:
            raise ClientShapeError(f"unknown status case {case!r}")


def _normalized(text: str) -> str:
    """An operation on one line, whichever way Effect's formatter broke it,
    with the type of its ``options`` argument dropped."""
    rest = re.sub(r"\s+", " ", text).strip().removesuffix(",")
    rest = re.sub(r'options: Parameters<\w+\["\w+"\]>\[\d+\]', "options", rest)
    return re.sub(r" \)", ")", re.sub(r"\( ", "(", rest)).replace(") .pipe(", ").pipe(")


def _encoded_template(path: str, values: tuple[str, ...]) -> str:
    """``"/a/" + __encodePathParam(x) + "/b"`` as ``/a/{}/b``."""
    template: list[str] = []
    encoded: list[str] = []
    for part in path.split(" + "):
        if literal := _PATH_LITERAL.match(part):
            template.append(literal.group(1))
        elif parameter := _ENCODED_PARAMETER.match(part):
            template.append("{}")
            encoded.append(parameter.group(1))
        else:
            raise ClientShapeError(f"unknown path part {part!r}")
    if tuple(encoded) != values:
        raise ClientShapeError("the checked and the encoded path parameters differ")
    return "".join(template)


def _start(name: str, args: tuple[str, ...], rest: str) -> tuple[Operation, str]:
    """The operation's method and path, and its request's steps, each form
    of which ends in the one ``)`` of a plain ``.pipe(``."""
    if match := _PLAIN_REQUEST.match(rest):
        path = match.group("template")
        if path is None:
            path = match.group("literal")
        return Operation(name, match.group("method").upper(), path, args), rest[match.end() :]
    match = _CHECKED_REQUEST.match(rest)
    if match is None:
        raise ClientShapeError(f"unknown request {rest[:80]!r}")
    values = tuple(value.strip() for value in match.group("values").split(","))
    closing = "))" + (")" if match.group("stream") else "")
    if not rest.endswith(closing):
        raise ClientShapeError(f"unknown end of request {rest[-20:]!r}")
    if match.group("stream") and match.group("lift") != "map":
        raise ClientShapeError("a stream that is not a mapped request")
    operation = Operation(
        name,
        match.group("method").upper(),
        _encoded_template(match.group("path"), values),
        args,
        encoded_path=True,
    )
    return operation, rest[match.end() : -len(closing)]


def _operation(text: str) -> Operation:
    rest = _normalized(text)
    head = _HEAD.match(rest)
    if head is None:
        raise ClientShapeError(f"unknown operation head {rest[:80]!r}")
    args = tuple(arg.strip() for arg in head.group("args").split(","))
    path_args = tuple(arg for arg in args if arg != "options")
    operation, rest = _start(head.group("name"), path_args, rest[head.end() :])
    if match := _URL_PARAMS.match(rest):
        operation.url_params = _entries(match.group("entries"), _URL_ENTRY, "query")
        rest = rest[match.end() :]
    if match := _HEADERS.match(rest):
        operation.headers = _entries(match.group("entries"), _HEADER_ENTRY, "header")
        rest = rest[match.end() :]
    if match := _BODY.match(rest):
        operation.body = "json" if match.group("body").startswith("bodyJson") else "form"
        rest = rest[match.end() :]
    if match := _JSON.match(rest):
        _status_cases(operation, match.group("cases").removesuffix(" ").removesuffix(","))
    elif match := _SSE.match(rest):
        operation.kind = "sse"
        operation.stream_schema = match.group("schema")
    elif _BINARY.match(rest):
        operation.kind = "binary"
    else:
        raise ClientShapeError(f"unknown response handling {rest[:80]!r}")
    return operation


def operations(source: str) -> list[Operation]:
    start = source.find("  return {\n    httpClient,\n")
    end = source.find("\nexport interface ", start)
    if start < 0 or end < 0:
        raise ClientShapeError("no generated client found")
    body = source[start:end].split("\n")[2:]
    chunks: list[list[str]] = []
    for line in body:
        if re.match(r'^    "\w+": \(', line):
            chunks.append([])
        if chunks:
            chunks[-1].append(line)
    found: list[Operation] = []
    for chunk in chunks:
        text = "\n".join(chunk)
        text = re.sub(r"\n  \}\n\}\s*$", "", text)
        name = re.match(r'^    "(\w+)"', text)
        try:
            found.append(_operation(text))
        except ClientShapeError as error:
            raise ClientShapeError(f"{name.group(1) if name else '?'}: {error}") from error
    return found


# --- the interface ----------------------------------------------------------------------


_PATH_ARGUMENT = re.compile(r'(?:^ +|^  readonly "\w+": \()(\w+): string(?:,?$|\) =>)', re.M)


def signatures(source: str, target: ClientTarget) -> dict[str, Signature]:
    start = source.find(f"export interface {target.client_name} {{")
    if start < 0:
        raise ClientShapeError(f"no interface {target.client_name}")
    end = source.find("\n}\n", start)
    lines = source[start:end].split("\n")[2:]
    found: dict[str, Signature] = {}
    doc: list[str] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        text = "\n".join(block)
        name = re.match(r'^  readonly "(\w+)"', text)
        if name is None:
            raise ClientShapeError(f"unknown interface member {block[0]!r}")
        params = re.search(r"readonly params(\??): typeof (\w+)\.Encoded", text)
        payload = re.search(r"readonly payload: typeof (\w+)\.Encoded", text)
        found[name.group(1)] = Signature(
            name.group(1),
            "\n".join(doc).strip(),
            tuple(dict.fromkeys(_PATH_ARGUMENT.findall(text))),
            params.group(2) if params else None,
            params is not None and params.group(1) == "",
            payload.group(1) if payload else None,
        )
        block.clear()

    in_doc = False
    for line in lines:
        stripped = line.strip()
        if stripped == "/**":
            flush()
            doc = []
            in_doc = True
        elif in_doc:
            if stripped == "*/":
                in_doc = False
            else:
                doc.append(stripped.removeprefix("*").removeprefix(" "))
        elif line.startswith('  readonly "'):
            flush()
            block.append(line)
        elif block:
            block.append(line)
    flush()
    return found


# --- emitting ---------------------------------------------------------------------------


def _docstring(text: str, indent: str) -> str:
    if not text:
        return ""
    escaped = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if escaped.endswith('"'):
        escaped += " "
    body = escaped.replace("\n", "\n" + indent)
    return f'{indent}"""{body}"""\n'


def _path(operation: Operation) -> str:
    path = operation.path
    if operation.encoded_path:
        arguments = "".join(f", {snake(arg)}" for arg in operation.path_args)
        return f'_c.encoded_path("{path}"{arguments})'
    if re.search(r"[{}]", re.sub(r"\$\{\w+\}", "", path)):
        raise ClientShapeError(f"{operation.name}: braces in path {path!r}")
    names = {arg: snake(arg) for arg in operation.path_args}

    def arg(match: re.Match[str]) -> str:
        if match.group(1) not in names:
            raise ClientShapeError(f"{operation.name}: unknown path argument {match.group(1)}")
        return "{" + names[match.group(1)] + "}"

    replaced = re.sub(r"\$\{(\w+)\}", arg, path)
    return f'f"{replaced}"' if names else f'"{replaced}"'


def _constant(operation: Operation) -> str:
    return "_" + snake(operation.name).upper()


def _operation_line(operation: Operation) -> str:
    parts = [f'"{operation.method}"']
    if operation.url_params:
        parts.append(f"url_params=({''.join(f'{k!r}, ' for k in operation.url_params)})")
    if operation.headers:
        parts.append(f"headers=({''.join(f'{k!r}, ' for k in operation.headers)})")
    if operation.success is not None:
        parts.append(f"success={operation.success}")
    if operation.status_success:
        cases = ", ".join(f"{status}: {schema}" for status, schema in operation.status_success)
        parts.append(f"status_success={{{cases}}}")
    if operation.binary_success:
        parts.append("binary_success=True")
    if operation.void:
        parts.append(f"void=({''.join(f'{status}, ' for status in operation.void)})")
    if operation.errors:
        cases = ", ".join(
            f"{status}: ({tag!r}, {schema})" for status, tag, schema in operation.errors
        )
        parts.append(f"errors={{{cases}}}")
    return f"{_constant(operation)} = _c.Operation({', '.join(parts)})"


def _arguments(operation: Operation, signature: Signature, include: str | None) -> str:
    args = ["self", *(f"{snake(arg)}: str" for arg in operation.path_args), "*"]
    if signature.payload is not None:
        args.append(f"payload: _T.{signature.payload}")
    if signature.params is not None:
        if signature.params_required:
            args.append(f"params: _T.{signature.params}")
        else:
            args.append(f"params: _T.{signature.params} | None = None")
    if include is not None:
        args.append(include)
    if args[-1] == "*":
        args.pop()
    return ", ".join(args)


def _call(operation: Operation, signature: Signature, method: str, *extra: str) -> str:
    params = "params" if signature.params is not None else "None"
    if signature.payload is None:
        body = "None"
    else:
        body = f"_c.{'json' if operation.body == 'json' else 'form'}_body(payload)"
    args = ", ".join([_constant(operation), _path(operation), params, body, *extra])
    return f"        return self.{method}({args})\n"


def _success_type(operation: Operation) -> str:
    if operation.binary_success:
        return "bytes"
    if operation.status_success:
        return " | ".join(f"_T.{schema}" for _, schema in operation.status_success)
    return "None" if operation.success is None else f"_T.{operation.success}"


def _method(operation: Operation, signature: Signature, types: set[str]) -> str:
    name = snake(operation.name)
    doc = _docstring(signature.doc, "        ")
    for type_name in (
        signature.params,
        signature.payload,
        operation.success,
        operation.stream_schema,
        *(schema for _, schema in operation.status_success),
    ):
        if type_name is not None and type_name not in types:
            raise ClientShapeError(f"{operation.name}: no type {type_name}")
    if operation.kind == "sse":
        result = f"_Stream[_sse.DataEvent[_T.{operation.stream_schema}], _SseErrors]"
        head = f"    def {name}({_arguments(operation, signature, None)}) -> {result}:\n"
        return head + doc + _call(operation, signature, "_sse", str(operation.stream_schema))
    if operation.kind == "binary":
        result = "_Stream[bytes, _HttpClientError]"
        head = f"    def {name}({_arguments(operation, signature, None)}) -> {result}:\n"
        return head + doc + _call(operation, signature, "_binary")
    has_body = operation.success is not None or operation.status_success or operation.binary_success
    if has_body and operation.void:
        raise ClientShapeError(f"{operation.name}: both a success body and a void status")
    success = _success_type(operation)
    errors = "_Errors" if operation.errors else "_PlainErrors"
    plain = _arguments(operation, signature, "include_response: _t.Literal[False] = False")
    tupled = _arguments(operation, signature, "include_response: _t.Literal[True]")
    either = _arguments(operation, signature, "include_response: bool = False")
    return (
        "    @_t.overload\n"
        f"    def {name}({plain}) -> _Effect[{success}, {errors}]: ...\n"
        "    @_t.overload\n"
        f"    def {name}({tupled}) -> "
        f"_Effect[tuple[{success}, _HttpClientResponse], {errors}]: ...\n"
        f"    def {name}({either}) -> _Effect[_t.Any, {errors}]:\n"
        + doc
        + _call(operation, signature, "_json", "include_response")
    )


def _header(target: ClientTarget, schemas: list[str]) -> str:
    imports = "".join(f"    {name},\n" for name in schemas)
    return f'''"""Effect's generated ``{target.client_name}``: a method per operation of the
{target.title} API, generated from Effect's ``Generated.ts`` by
``scripts/gen_ai_schemas.py``; do not edit.

A JSON operation gives its decoded body (with ``include_response=True``,
the body and the response); a documented error status fails with
``{target.client_title}ClientError`` (``tag`` names the operation and status,
``cause`` is the decoded body). ``...Sse`` operations stream the decoded
events, ``...Stream`` ones the body's bytes.
"""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import typing as _t

from pyfect import schema as _S
from pyfect._core import Effect as _Effect
from pyfect.ai import _generated_client as _c
from pyfect.encoding import sse as _sse
from pyfect.http.client import HttpClientService as _HttpClientService
from pyfect.http.error import HttpClientError as _HttpClientError
from pyfect.http.response import HttpClientResponse as _HttpClientResponse
from pyfect.stream import Stream as _Stream
from {target.package} import types as _T
from {target.package} import (
{imports})


class {target.client_title}ClientError(_c.ClientError):
    """A documented error status of an operation."""


type _Errors = _HttpClientError | _S.SchemaError | {target.client_title}ClientError
type _PlainErrors = _HttpClientError | _S.SchemaError
type _SseErrors = _HttpClientError | _S.SchemaError | _sse.Retry | _sse.SseError

'''


_STREAMS_ARE_TRANSFORMED = "const executeStreamRequest = "
_TRANSFORM_STREAMS = "    transform_streams = True\n"


def generate_client(source: str, target: ClientTarget, types: set[str]) -> str:
    found = operations(source)
    signed = signatures(source, target)
    if [operation.name for operation in found] != list(signed):
        raise ClientShapeError("the implementation and the interface name different operations")
    methods = [snake(operation.name) for operation in found]
    if len(set(methods)) != len(methods):
        raise ClientShapeError("two operations have the same method name")
    schemas: set[str] = set()
    for operation in found:
        if operation.success is not None:
            schemas.add(operation.success)
        if operation.stream_schema is not None:
            schemas.add(operation.stream_schema)
        schemas.update(schema for _, schema in operation.status_success)
        schemas.update(schema for _, _, schema in operation.errors)
        signature = signed[operation.name]
        if signature.path_args != operation.path_args:
            raise ClientShapeError(f"{operation.name}: path arguments differ")
        if (signature.payload is None) != (operation.body is None):
            raise ClientShapeError(f"{operation.name}: payload and body differ")
    streams_transformed = _STREAMS_ARE_TRANSFORMED in source
    transformed = "each operation" if streams_transformed else "each JSON operation"
    lines = [_header(target, sorted(schemas))]
    lines.extend(_operation_line(operation) + "\n" for operation in found)
    lines.append(
        f"\n\nclass {target.client_name}(_c.GeneratedClient):\n"
        f'    """The {target.title} API: build it with ``make``."""\n\n'
        f"    __slots__ = ()\n\n"
        f"    error_class = {target.client_title}ClientError\n"
        f"{_TRANSFORM_STREAMS if streams_transformed else ''}\n"
    )
    lines.append("\n".join(_method(op, signed[op.name], types) for op in found))
    lines.append(
        f"""

def make(
    http_client: _HttpClientService[_HttpClientError],
    *,
    transform_client: _c.ClientTransform | None = None,
) -> {target.client_name}:
    \"\"\"The client over ``http_client`` (requests carry relative paths:
    prepend the API's URL to the client). ``transform_client`` picks the
    client {transformed} runs on, per call.\"\"\"
    return {target.client_name}(http_client, transform_client)


__all__ = ["{target.client_name}", "{target.client_title}ClientError", "make"]
"""
    )
    return "".join(lines)
