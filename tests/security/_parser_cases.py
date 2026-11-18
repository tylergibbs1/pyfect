"""The parsers and decoders of peer input, each with the inputs that cost it the most.

``CASES`` measures growth (``_growth.assert_near_linear``); ``AMPLIFIED`` compares a
costly input with plain text of the same length, for work that is linear but huge per byte
or only slightly superlinear (big-int conversion, regex compilation). ``text`` registers a
function of one string against every input of ``ADVERSARIES``; ``channel`` does the same for
a streaming decoder, with the input in one chunk and in small pieces. ``NOT_MEASURED`` says
why a parser-like public function is not here. ``test_every_parser_is_measured`` fails on a
public parser in neither, so a new one cannot ship without a case.

A case with ``fixed_elsewhere`` is a lead fixed on another branch, run as a strict xfail; the
integrator removes it after merging (the run fails once the case passes).
"""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import io
import json
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from itertools import cycle, islice
from typing import Any, TypedDict, cast

from _growth import MAX_SIZE, Make, Work

import pyfect as fx
from pyfect import (
    big_decimal,
    byte_size,
    channel_schema,
    cron,
    date_time,
    duration,
    json_patch,
    json_pointer,
    process,
    rational,
    semver,
    semver_range,
    stream,
    terminal,
)
from pyfect import channel as channel_module
from pyfect import schema as S
from pyfect.ai import mcp_schema, mcp_server
from pyfect.ai import tool as ai_tool
from pyfect.ai.chat import from_json as chat_from_json
from pyfect.cluster import shard_id, snowflake
from pyfect.crypto import key_format
from pyfect.effect import Effect
from pyfect.encoding import (
    base64,
    base64_url,
    csv,
    hex,
    ini,
    json5,
    json_array,
    jsonc,
    ndjson,
    schema_binary,
    sse,
    tar,
    toml,
    xml,
    yaml,
    zip,
)
from pyfect.eventlog import event_log, event_log_session_auth
from pyfect.exit import Success
from pyfect.graphql import client_error
from pyfect.http import (
    cookies,
    find_my_way,
    headers,
    middleware,
    multipart_parser,
    origin,
    server_request,
    static_server,
    url,
    url_params,
)
from pyfect.http import schema as http_schema
from pyfect.http.multipart_parser import PartInfo
from pyfect.http.web import WebRequest
from pyfect.jose import jwe, jwks, jws, jwt
from pyfect.net import dns, host, ip_interface, ip_network, net_address
from pyfect.rpc import serialization
from pyfect.sql.clickhouse import driver as clickhouse
from pyfect.sql.libsql import config as libsql_config
from pyfect.sql.mysql import config as mysql_config


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    target: object
    """The public function or schema measured, for ``test_every_parser_is_measured``."""
    make: Make
    size: int = 1000
    max_size: int = MAX_SIZE
    fixed_elsewhere: str | None = None
    """Why the case still fails here: a lead fixed on another branch, flipped at merge."""


@dataclass(frozen=True, slots=True)
class Amplified:
    id: str
    target: object
    costly: Work
    plain: Work
    """The same parser on plain input of the same length."""
    bound: float = 2


CASES: list[Case] = []
AMPLIFIED: list[Amplified] = []


def case(
    target: object,
    id: str,
    *,
    size: int = 1000,
    max_size: int = MAX_SIZE,
    fixed_elsewhere: str | None = None,
) -> Callable[[Make], Make]:
    def register(make: Make) -> Make:
        CASES.append(Case(id, target, make, size, max_size, fixed_elsewhere))
        return make

    return register


def settle(value: object) -> None:
    """Runs ``value`` when it is an effect, so its work counts."""
    if isinstance(value, Effect):
        fx.run_blocking_exit(value)


def ignoring(run: Callable[[], object]) -> Work:
    """``run`` as work whose refusal of the input (any exception) still counts as its cost."""

    def work() -> None:
        try:
            settle(run())
        except Exception:
            return

    return work


def run_channel(
    elements: list[Any], channel: Any, *, chunk_size: int = 1, valid: bool = True
) -> Work:
    """``elements`` through ``channel`` (``chunk_size`` to a chunk), collected. A valid input
    must decode, or the case would measure an early refusal."""
    program = stream.from_iterable(elements, chunk_size=chunk_size).pipe_through_channel(channel)

    def work() -> None:
        exit = fx.run_blocking_exit(program.run_collect())
        assert not valid or isinstance(exit, Success), exit

    return work


# ------------------------------------------------------------------------- generic inputs

_LETTERS = ((0x4E00, 0x9FFF), (0xAC00, 0xD7A3), (0x3400, 0x4DBF), (0x20000, 0x2A6DF))
"""IDNA-valid letters, all distinct: about 80k of them."""


def distinct_letters(n: int) -> str:
    out: list[str] = []
    for low, high in _LETTERS:
        out.extend(chr(code) for code in range(low, min(high + 1, low + n - len(out))))
    return "".join(out)


def _repeat(unit: str) -> Callable[[int], str]:
    return lambda n: unit * max(n // len(unit), 1)


def _cycled(units: str) -> Callable[[int], str]:
    return lambda n: "".join(islice(cycle(units), n))


ADVERSARIES: dict[str, Callable[[int], str]] = {
    "letters": _repeat("a"),
    "digits": _repeat("7"),
    "escapes": _repeat("%25"),
    "quoted": lambda n: '"' + '\\"' * (n // 2),
    "brackets": _repeat("["),
    "separators": _cycled(".-:;,=/ @#&?+*!"),
    "labels": _repeat("a."),
    "lines": _repeat("a\n"),
    "non-ASCII": lambda n: "".join(islice(cycle(distinct_letters(80_000)), n)),
}
"""Text that sends a parser down its slowest paths: long runs of one kind of token, escapes,
nesting, separators, many lines, many distinct characters."""


def _name(target: object) -> str:
    return getattr(target, "__qualname__", None) or type(target).__name__


def _qualified(target: object) -> str:
    return f"{getattr(target, '__module__', '')}.{_name(target)}"


def text(target: Callable[..., object], call: Callable[[str], object] | None = None) -> None:
    """``target`` (or ``call``, a function of one string calling it) on every adversary."""
    run = call or target
    for kind, make_input in ADVERSARIES.items():

        def make(n: int, make_input: Callable[[int], str] = make_input) -> Work:
            value = make_input(n)
            return ignoring(lambda: run(value))

        CASES.append(Case(f"{_qualified(target)}: {kind}", target, make))


def data(target: Callable[..., object], call: Callable[[bytes], object] | None = None) -> None:
    """``text`` for a function of bytes."""
    run = call or target
    for kind, make_input in ADVERSARIES.items():

        def make(n: int, make_input: Callable[[int], str] = make_input) -> Work:
            value = make_input(n).encode()
            return ignoring(lambda: run(value))

        CASES.append(Case(f"{_qualified(target)}: {kind}", target, make))


def channel(target: object, make_channel: Callable[[], Any], *, is_bytes: bool = False) -> None:
    """A streaming decoder on every adversary, in one chunk and in 16-character pieces."""
    for kind, make_input in ADVERSARIES.items():
        for piece in (0, 16):

            def make(
                n: int, make_input: Callable[[int], str] = make_input, piece: int = piece
            ) -> Work:
                value: Any = make_input(n).encode() if is_bytes else make_input(n)
                chunks = (
                    [value]
                    if piece == 0
                    else [value[i : i + piece] for i in range(0, len(value), piece)]
                )
                return run_channel(chunks, make_channel(), valid=False)

            how = "one chunk" if piece == 0 else f"{piece}-character pieces"
            CASES.append(Case(f"{_qualified(target)}: {kind}, {how}", target, make))


def schema(target: S.Top, name: str) -> None:
    """A schema decoding text, on every adversary. ``name`` names the cases: a schema's repr
    holds object addresses, which differ between processes."""
    decode = S.decode_unknown_exit(cast("Any", target))
    for kind, make_input in ADVERSARIES.items():

        def make(n: int, make_input: Callable[[int], str] = make_input) -> Work:
            value = make_input(n)
            return lambda: decode(value)

        CASES.append(Case(f"{name}: {kind}", target, make))


# ------------------------------------------------------------------------- text parsers

for _target in (
    big_decimal.from_string,
    big_decimal.from_string_unsafe,
    rational.from_string,
    rational.from_string_unsafe,
    byte_size.from_string,
    byte_size.from_string_unsafe,
    shard_id.from_string,
    shard_id.parse_signed_digits,
    cron.parse,
    cron.parse_unsafe,
    date_time.make_zoned_from_string,
    date_time.zone_from_string,
    duration.parse_iso_nanos,
    base64.decode_string,
    base64.decode_lenient,
    base64_url.decode_string,
    hex.decode,
    hex.decode_string,
    key_format.base64_decode,
    key_format.base64_url_decode,
    ini.parse,
    json5.parse,
    jsonc.parse,
    toml.parse,
    yaml.parse,
    sse.parse_digits,
    ai_tool.unsafe_secure_json_parse,
    ai_tool.parse_json_text,
    mcp_server.decode_routing_header,
    mcp_server.decode_name_header,
    mcp_schema.parse_request_id,
    chat_from_json,
    event_log.decode_identity_string,
    event_log.base64_decode,
    event_log.base64_url_decode,
    origin.parse_authority,
    origin.parse_origin,
    server_request.parse_origin_form,
    server_request.parse_content_length,
    headers.parse_http_date,
    headers.parse_retry_after,
    middleware.parse_accept_encoding,
    middleware.parse_content_encoding,
    url.from_string,
    url.parse,
    url_params.parse,
    jwe.decode_segment,
    jws.parse,
    jwt.decode_unverified,
    json_pointer.parse_uri_fragment,
    dns.name_server_from_string,
    host.domain_name_from_string,
    host.host_from_string,
    host.host_port_from_string,
    host.parse_hosts_file,
    host.ip_from_string,
    host.scoped_ipv6_literal_from_string,
    ip_interface.from_string,
    ip_interface.from_string_unsafe,
    ip_interface.ipv4_from_string,
    ip_interface.ipv6_from_string,
    ip_interface.parse_ipv4,
    ip_interface.parse_ipv6,
    ip_network.from_string,
    ip_network.from_string_unsafe,
    ip_network.ipv4_from_string,
    ip_network.ipv6_from_string,
    net_address.inet_address_from_string,
    net_address.mac_address_from_string,
    process.parse_fd_name,
    semver.parse,
    semver.parse_unsafe,
    semver_range.parse,
    semver_range.parse_unsafe,
    clickhouse.parse_error,
    mysql_config.parse_url,
    mysql_config.parse_query,
    terminal.decode,
):
    text(_target)

text(
    client_error.parse_retry_after_header,
    lambda value: client_error.parse_retry_after_header(value, 0),
)
text(static_server.parse_range, lambda value: static_server.parse_range(value, 1 << 40))
text(semver.parse_component, lambda value: semver.parse_component(value, "major"))
text(libsql_config.parse_target, lambda value: libsql_config.parse_target(value, None, None))
data(jwks.parse_json_object)


def _session_auth_payload(value: str) -> bytes:
    """A canonical payload whose three variable fields each hold ``value``: the adversaries
    as bytes are refused at the first length prefix, which measures nothing."""
    payload = event_log_session_auth.SessionAuthPayload(
        remote_id=value,
        challenge=value.encode(),
        public_key=value,
        signing_public_key=bytes(event_log_session_auth.ED25519_PUBLIC_KEY_LENGTH),
    )
    return fx.run_blocking(event_log_session_auth.encode_session_auth_payload(payload).or_die())


for _kind, _make_input in ADVERSARIES.items():

    def _session_auth(n: int, make_input: Callable[[int], str] = _make_input) -> Work:
        decode = event_log_session_auth.decode_session_auth_payload
        data = _session_auth_payload(make_input(n // 3))
        return lambda: fx.run_blocking(decode(data).or_die())

    CASES.append(
        Case(
            f"{_qualified(event_log_session_auth.decode_session_auth_payload)}: {_kind}",
            event_log_session_auth.decode_session_auth_payload,
            _session_auth,
            size=1 << 16,  # copying a field is cheap: below this, the call's fixed cost hides it
        )
    )


@case(
    cookies.parse_header,
    "cookies.parse_header: many empty pairs (#49)",
)
def _cookie_pairs(n: int) -> Work:
    value = ";" * n + "=x"
    return lambda: cookies.parse_header(value)


text(cookies.parse_header)


def _punycode_field(n: int) -> Work:
    info = PartInfo(
        "f", None, "text/plain", {"charset": "punycode"}, "form-data", {"name": "f"}, {}
    )
    value = b"A" * n
    return lambda: multipart_parser.decode_field(info, value)


CASES.append(
    Case(
        "multipart_parser.decode_field: a punycode field (#26)",
        multipart_parser.decode_field,
        _punycode_field,
        size=64_000,
    )
)


def _router_escapes(n: int) -> Work:
    routes: find_my_way.Router[str] = find_my_way.Router()
    routes.on("GET", "/notes/:id", "note")
    path = "/notes/" + "%25" * n
    return lambda: routes.find("GET", path)


CASES.append(
    Case(
        "find_my_way.Router.find: a path of escaped percent signs (#50)",
        find_my_way.Router.find,
        _router_escapes,
        size=16_000,
    )
)


def _repeated_header(n: int) -> Work:
    lines = [("x", "a")] * n
    return lambda: WebRequest("http://test/", headers=lines).headers


CASES.append(
    Case(
        "WebRequest.headers: many lines of one header (#57)",
        WebRequest,
        _repeated_header,
        size=4000,
    )
)


# ------------------------------------------------------------------------- streaming decoders

channel(channel_module.decode_text, channel_module.decode_text, is_bytes=True)
channel(csv.decode_string, csv.decode_string)
channel(csv.decode, csv.decode, is_bytes=True)
channel(csv.decode_schema_string, lambda: csv.decode_schema_string(S.Array(S.String)))
channel(csv.decode_schema, lambda: csv.decode_schema(S.Array(S.String)), is_bytes=True)
channel(json_array.decode_string, json_array.decode_string)
channel(json_array.decode, json_array.decode, is_bytes=True)
channel(json_array.decode_schema_string, lambda: json_array.decode_schema_string(S.Unknown))
channel(json_array.decode_schema, lambda: json_array.decode_schema(S.Unknown), is_bytes=True)
channel(ndjson.decode_string, ndjson.decode_string)
channel(ndjson.decode, ndjson.decode, is_bytes=True)
channel(ndjson.decode_schema_string, lambda: ndjson.decode_schema_string(S.Unknown))
channel(ndjson.decode_schema, lambda: ndjson.decode_schema(S.Unknown), is_bytes=True)
channel(sse.decode, sse.decode)
channel(sse.decode_schema, lambda: sse.decode_schema(S.Record(S.String, S.Unknown)))
channel(sse.decode_data_schema, lambda: sse.decode_data_schema(S.Unknown))
channel(xml.decode_string, xml.decode_string)
channel(xml.decode, xml.decode, is_bytes=True)
channel(tar.decode, tar.decode, is_bytes=True)
channel(zip.decode, zip.decode, is_bytes=True)
channel(schema_binary.decode, lambda: schema_binary.decode(S.Unknown), is_bytes=True)
channel(channel_schema.decode_unknown, lambda: channel_schema.decode_unknown(S.String))
channel(channel_schema.decode, lambda: channel_schema.decode(S.String))


@case(xml.decode, "xml.decode: a comment with a non-ASCII character in every chunk (#42)")
def _xml_non_ascii(n: int) -> Work:
    chunk = "é".encode() + b"a" * 62
    return run_channel([b"<r><!--", *[chunk] * n, b"--></r>"], xml.decode())


@case(
    xml.decode,
    "xml.decode: a leading comment with a non-ASCII character and ?> in every chunk (#42)",
)
def _xml_non_ascii_leading_comment(n: int) -> Work:
    # The first token, so the US-ASCII declaration is still undecided; a comment can't be it,
    # so no chunk may make the parser rescan it.
    chunk = "é?>".encode() + b"a" * 60
    return run_channel([b"<!--", *[chunk] * n, b"--><r/>"], xml.decode())


@case(xml.decode_string, "xml.decode_string: text split by CDATA sections (#43)", size=8000)
def _xml_cdata_text(n: int) -> Work:
    return run_channel(["<r>" + "xxxxxxxxxxxx<![CDATA[]]>" * n + "</r>"], xml.decode_string())


@case(xml.elements, "xml.elements: many text events in one element (#43)")
def _xml_collected_text(n: int) -> Work:
    events: list[xml.Event] = [
        xml.StartElement("r", {}),
        *([xml.Text("x" * 64), xml.Comment("")] * n),
        xml.EndElement("r"),
    ]
    return run_channel(events, xml.elements(["r"]), chunk_size=len(events))


@case(
    xml.decode_string, "xml.decode_string: tags in a chunk past max_token_size (#41)", size=20_000
)
def _xml_markup_window(n: int) -> Work:
    return run_channel(["<r>" + "<a/>" * n + "</r>"], xml.decode_string(max_token_size=64))


@case(xml.decode_string, "xml.decode_string: positions of many tags on one line")
def _xml_positions_one_line(n: int) -> Work:
    return run_channel(["<r>" + "<a/>" * n + "</r>"], xml.decode_string(positions=True))


@case(xml.decode, "xml.decode: positions of many tags over many lines, in small chunks")
def _xml_positions_lines(n: int) -> Work:
    document = ("<r>" + "<a/>\r\n" * n + "</r>").encode()
    chunks = [document[i : i + 16] for i in range(0, len(document), 16)]
    return run_channel(chunks, xml.decode(positions=True))


def _xml_events(n: int) -> tuple[xml.Event, ...]:
    events: list[xml.Event] = [xml.StartElement("r", {})]
    for _ in range(n):
        events += [xml.StartElement("a", {}), xml.EndElement("a")]
    return (*events, xml.EndElement("r"))


@case(xml.encode_string, "xml.encode_string: many events in one chunk (#44)")
def _xml_encode_string(n: int) -> Work:
    events = _xml_events(n)
    return run_channel(list(events), xml.encode_string(), chunk_size=len(events))


@case(xml.encode, "xml.encode: many events in one chunk (#44)")
def _xml_encode(n: int) -> Work:
    events = _xml_events(n)
    return run_channel(list(events), xml.encode(), chunk_size=len(events))


def _tar_with_global_records(n: int) -> bytes:
    """A global PAX header of ``n`` short records, then ``n // 16`` empty entries."""
    out = io.BytesIO()
    records = {f"k{i:07}": "1" for i in range(n)}
    with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT, pax_headers=records) as t:
        for i in range(n // 16):
            info = tarfile.TarInfo(f"d{i}")
            info.type = tarfile.DIRTYPE
            t.addfile(info)
    return out.getvalue()


@case(tar.decode, "tar.decode: global PAX records before many entries (#24)", size=256)
def _tar_global_records(n: int) -> Work:
    return run_channel([_tar_with_global_records(n)], tar.decode())


class _Payload(TypedDict):
    n: float


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        low, n = n & 0x7F, n >> 7
        if not n:
            out.append(low)
            return bytes(out)
        out.append(low | 0x80)


@case(
    schema_binary.parser,
    "schema_binary: a long big-varint run in an RPC payload (#70)",
    size=16_000,
)
def _schema_binary_varint(n: int) -> Work:
    codec = serialization.make_schema_binary().codec_for(S.Struct(_Payload))
    decode = S.decode_unknown_exit(codec)
    base = S.encode_unknown_sync(codec)({"n": 1})
    payload = base[1:-1] + b"\xff" * n + b"\x02"
    frame = _varint(len(payload)) + payload
    return lambda: decode(frame)


@case(
    serialization.json_rpc,
    "rpc json_rpc: a batch of hash-colliding integer ids (#27)",
    size=2000,
)
def _json_rpc_ids(n: int) -> Work:
    collide = 2**61 - 1
    body = json.dumps([{"jsonrpc": "2.0", "method": "m", "id": i * collide} for i in range(1, n)])
    return ignoring(lambda: serialization.json_rpc().make_unsafe().decode(body))


# ------------------------------------------------------------------------- lead inputs


@case(url.from_string, "url: a host of distinct non-ASCII letters (#72)", max_size=80_000)
def _url_host(n: int) -> Work:
    value = f"https://{distinct_letters(n)}/"
    return lambda: url.from_string(value)


@case(
    url.from_string,
    "url: distinct non-ASCII letters under the host limit (#72)",
    size=300,
    max_size=5400,
)
def _url_host_under_limit(n: int) -> Work:
    value = f"https://{distinct_letters(n)}/"
    return lambda: url.from_string(value)


@case(url.from_string, "url: a host of joiners between joining letters (#72)")
def _url_joiners(n: int) -> Work:
    value = f"https://{'ب‌' * n}ب/"
    return lambda: url.from_string(value)


@case(S.URLFromString, "URLFromString: distinct non-ASCII letters (#72)", max_size=80_000)
def _url_schema(n: int) -> Work:
    value = f"https://{distinct_letters(n)}/"
    decode = S.decode_unknown_exit(S.URLFromString)
    return lambda: decode(value)


@case(yaml.parse, "yaml.parse: a flow sequence over many lines (#45)", size=50_000)
def _yaml_flow_lines(n: int) -> Work:
    value = "[\n" + "1,\n" * n + "]"
    return lambda: yaml.parse(value)


@case(toml.parse, "toml.parse: a table header of many dotted keys (#40)")
def _toml_header(n: int) -> Work:
    value = "[" + ".".join(["a"] * n) + "]"
    return lambda: toml.parse(value)


@case(json_patch.apply, "json_patch.apply: many appends to one array (#59)")
def _json_patch_appends(n: int) -> Work:
    patch: Any = [{"op": "add", "path": "/-", "value": 0}] * n
    return lambda: json_patch.apply(patch, [])


@case(json_patch.apply, "json_patch.apply: many keys added to a nested object (#59)")
def _json_patch_nested(n: int) -> Work:
    patch: Any = [{"op": "add", "path": f"/a/b/k{i}", "value": i} for i in range(n)]
    return lambda: json_patch.apply(patch, {"a": {"b": {}}})


@case(S.BigDecimalFromString, "BigDecimalFromString: a long digit run (#31)")
def _big_decimal_digits(n: int) -> Work:
    decode = S.decode_unknown_exit(S.BigDecimalFromString)
    value = "7" * n
    return lambda: decode(value)


@case(S.BigDecimalFromString, "BigDecimalFromString: a long exponent (#31)")
def _big_decimal_exponent(n: int) -> Work:
    decode = S.decode_unknown_exit(S.BigDecimalFromString)
    value = f"1e{'7' * n}"
    return lambda: decode(value)


@case(S.RegExp, "RegExp JSON: flags of distinct characters (#67)", max_size=500_000)
def _regexp_flags(n: int) -> Work:
    decode = S.decode_unknown_exit(S.to_codec_json(S.RegExp))
    value = {"source": "a", "flags": "".join(chr(0x100 + i) for i in range(n))}
    return lambda: decode(value)


@case(
    S.FrozenSet,
    "FrozenSet(Number) JSON: hash-colliding integers (#25)",
)
def _frozen_set_collisions(n: int) -> Work:
    decode = S.decode_unknown_exit(S.to_codec_json(S.FrozenSet(S.Number)))
    value = [i * (2**61 - 1) for i in range(1, n)]
    return lambda: decode(value)


# ------------------------------------------------------------------------- schemas of text

for _name_ in dir(S):
    if _name_.endswith("FromString"):
        schema(getattr(S, _name_), f"S.{_name_}")
schema(snowflake.SnowflakeFromString, "snowflake.SnowflakeFromString")
schema(http_schema.RetryAfterFromString, "http_schema.RetryAfterFromString")
schema(S.to_codec_json(S.RegExp), "S.to_codec_json(S.RegExp)")
schema(S.UnknownFromJsonString, "S.UnknownFromJsonString")
schema(S.BigDecimal.pipe(S.to_codec_json), "S.BigDecimal.pipe(S.to_codec_json)")


# ------------------------------------------------------------------------- amplification

_BIG = 1 << 20


def _amplified(
    target: object, id: str, costly: Callable[[], object], plain: Callable[[], object]
) -> None:
    AMPLIFIED.append(Amplified(id, target, ignoring(costly), ignoring(plain)))


_decode_big_decimal = S.decode_unknown_exit(S.BigDecimalFromString)
_amplified(
    S.BigDecimalFromString,
    "BigDecimalFromString: a long digit run, hashed (#31)",
    lambda: hash(_decode_big_decimal("7" * _BIG)),
    lambda: hash(_decode_big_decimal("a" * _BIG)),
)
_amplified(
    S.BigDecimalFromString,
    "BigDecimalFromString: a long exponent (#31)",
    lambda: _decode_big_decimal("1e" + "7" * _BIG),
    lambda: _decode_big_decimal("a" * _BIG),
)
_amplified(
    yaml.parse,
    "yaml.parse: a long hexadecimal key (#32)",
    lambda: yaml.parse(f"0x{'f' * _BIG}: 1"),
    lambda: yaml.parse(f"{'g' * _BIG}: 1"),
)
_amplified(
    yaml.parse,
    "yaml.parse: a long decimal key (#32)",
    lambda: yaml.parse(f"{'7' * _BIG}: 1"),
    lambda: yaml.parse(f"{'g' * _BIG}: 1"),
)


# ------------------------------------------------------------------------- not measured

_REASONS: dict[str, list[str]] = {
    "runs a schema; schemas of text are measured": [
        "pyfect.schema._parse.decode_effect",
        "pyfect.schema._parse.decode_exit",
        "pyfect.schema._parse.decode_option",
        "pyfect.schema._parse.decode_promise",
        "pyfect.schema._parse.decode_result",
        "pyfect.schema._parse.decode_sync",
        "pyfect.schema._parse.decode_unknown_effect",
        "pyfect.schema._parse.decode_unknown_exit",
        "pyfect.schema._parse.decode_unknown_option",
        "pyfect.schema._parse.decode_unknown_promise",
        "pyfect.schema._parse.decode_unknown_result",
        "pyfect.schema._parse.decode_unknown_sync",
    ],
    "checks provider JSON already parsed by the measured JSON parser against a schema": [
        "pyfect.ai._provider.wire_decoder.<locals>.decode",
    ],
    "builds a transformation; parses nothing": [
        "pyfect.schema._transform.decode",
    ],
    "builds a schema; parses nothing": [
        "pyfect.schema._transform.decode_to",
    ],
    "one step of a schema's decoding": [
        "pyfect.schema.ast._declaration.parse_at_key",
    ],
    "builds an AST; parses nothing": [
        "pyfect.schema.ast._encoding.decode_to",
    ],
    "compiles a schema; parses nothing": [
        "pyfect.schema.compiler.runtime.decode",
    ],
    "builds a codec; UnknownFromJsonString is measured": [
        "pyfect.schema._codecs.from_json_string",
    ],
    "builds a transformation; UnknownFromJsonString is measured": [
        "pyfect.schema.transformation._builtins.from_json_string",
    ],
    "builds a getter; the base64 decoders are measured": [
        "pyfect.schema.getter._binary.decode_base64",
        "pyfect.schema.getter._binary.decode_base64_string",
        "pyfect.schema.getter._binary.decode_base64_url",
        "pyfect.schema.getter._binary.decode_base64_url_string",
    ],
    "builds a getter; the hex decoders are measured": [
        "pyfect.schema.getter._binary.decode_hex",
        "pyfect.schema.getter._binary.decode_hex_string",
    ],
    "builds a getter; JSON parsing is measured": [
        "pyfect.schema.getter._coerce.parse_json",
    ],
    "builds a getter; decode_uri_component is measured": [
        "pyfect.schema.getter._text.decode_uri_component",
    ],
    "a JSON Schema document the app loads": [
        "pyfect.schema.representation._import.from_json_schema_document",
        "pyfect.schema.representation._import.from_json_schema_multi_document",
    ],
    "a schema representation the app loads": [
        "pyfect.schema.representation._json.from_json",
        "pyfect.schema.representation._json.from_json_multi_document",
    ],
    "reads one header or cookie through the router's parsers": [
        "pyfect.http_api._security.security_decode",
    ],
    "builds a response decoder from schemas": [
        "pyfect.http_api.client.decode_response",
    ],
    "a schema decode of a message between runners of one cluster": [
        "pyfect.cluster.envelope.decode",
    ],
    "a schema decode of a reply between runners of one cluster": [
        "pyfect.cluster.reply.decode",
    ],
    "a schema decode of each message; json_rpc is measured": [
        "pyfect.rpc.message.decode_from_server",
    ],
    "matches one already-decoded message's tag and id; constant work": [
        "pyfect.rpc.message.decode_control",
    ],
    "schema_binary frames; schema_binary is measured (#70)": [
        "pyfect.eventlog.event_log_message.decode_changes_encrypted",
        "pyfect.eventlog.event_log_message.decode_changes_unencrypted",
        "pyfect.eventlog.event_log_message.decode_compaction_input_headers",
        "pyfect.eventlog.event_log_message.decode_compaction_segment",
    ],
    "the error wrapper of semver.parse, measured": [
        "pyfect.semver.try_parse",
    ],
    "reads a body under a byte limit; parses nothing": [
        "pyfect.http.server_request.read_limited",
    ],
    "key material the app loads, read by cryptography": [
        "pyfect.crypto.key_format.decode_private",
        "pyfect.crypto.key_format.decode_public",
        "pyfect.crypto.key_format.decode_secret",
    ],
    "builds a param for a file the CLI's user names": [
        "pyfect.cli.param.file_parse",
    ],
    "builds a primitive for a file the CLI's user names": [
        "pyfect.cli.primitive.file_parse",
    ],
    "builds an atom; parses nothing": [
        "pyfect.reactivity.atom._types.readable",
    ],
    "reads a socket; parses nothing": [
        "pyfect.socket._socket.reader_bytes",
        "pyfect.socket._socket.reader_string",
    ],
}
NOT_MEASURED: dict[str, str] = {name: why for why, names in _REASONS.items() for name in names}
"""Each parser-like public function no case measures, with the reason."""
