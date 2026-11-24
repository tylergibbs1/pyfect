"""Generate ``src/pyfect/protobuf/descriptor_proto.py``, the types and
descriptors of ``google/protobuf/descriptor.proto``, as Effect's
``scripts/protobuf/generate.mjs`` generates ``ProtobufDescriptorProto.ts``:
``uv run python scripts/gen_protobuf_descriptor.py [--check]``.

The input is ``tests/fixtures/protobuf/descriptor-set.binpb``, Effect's
fixture: ``protoc`` 36.2 output, with source information, for
``descriptor.proto`` and ``compiler/plugin.proto`` of protobuf v36.2. The
script checks its SHA-256 and reads it with pyfect's own ``message.decode``
and the descriptors of the module on disk, so the module supplies the
definitions that produce its next version. ``--check`` fails when the module
differs from the output. ``--bootstrap descriptor.json`` reads the fixture
with descriptors resolved from a JSON ``FileDescriptorProto`` instead, for
when the module is missing or broken.

As Effect's renderer, it handles only what ``descriptor.proto`` uses and
fails on anything else (a oneof, a field the descriptors do not know).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import keyword
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "protobuf" / "descriptor-set.binpb"
FIXTURE_SHA256 = "948853f065aa75d8f7ab994ac2c7ba493ec5868195e78d152c651e46529f80ac"
TARGET = ROOT / "src" / "pyfect" / "protobuf" / "descriptor_proto.py"
WIDTH = 100

_SCALARS = {
    1: "float",
    2: "float",
    3: "int",
    4: "int",
    5: "int",
    6: "int",
    7: "int",
    8: "bool",
    9: "str",
    12: "bytes",
    13: "int",
    15: "int",
    16: "int",
    17: "int",
    18: "int",
}
_TYPE_ENUM = 14
_LABEL_REQUIRED = 2
_LABEL_REPEATED = 3


def _descriptors(bootstrap: Path | None) -> tuple[Any, Any]:
    """The descriptors of ``FileDescriptorSet`` and ``FileDescriptorProto``."""
    if bootstrap is None:
        from pyfect.protobuf import descriptor_proto

        return descriptor_proto.FILE_DESCRIPTOR_SET, descriptor_proto.FILE_DESCRIPTOR_PROTO
    from pyfect.protobuf import _resolve

    file = _resolve.resolve([json.loads(bootstrap.read_text())]).files[0]
    return file.messages[0], file.messages[1]


def _compact(value: Mapping[Any, Any], descriptor: Any) -> dict[str, Any]:
    """``value`` with its fields in number order and no empty lists."""
    from pyfect.protobuf._binary import unknown_fields

    if unknown_fields in value:
        raise SystemExit(f"unknown fields in {descriptor.type_name}")
    known = {f.name for f in descriptor.fields}
    extra = set(value) - known
    if extra:
        raise SystemExit(f"{descriptor.type_name}: fields the descriptors do not know: {extra}")
    out: dict[str, Any] = {}
    for f in sorted(descriptor.fields, key=lambda f: f.number):
        item = value.get(f.name)
        if item is None or (f.kind == "list" and not item):
            continue
        is_message = f.type.kind == "message"

        def element(item: Any, f: Any = f, is_message: bool = is_message) -> Any:
            return _compact(item, f.type.message) if is_message else item

        out[f.name] = [element(i) for i in item] if f.kind == "list" else element(item)
    return out


def _literal(value: Any, depth: int = 0) -> str:
    if isinstance(value, bool):
        return repr(value)
    if isinstance(value, (int, float, bytes)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        parts = [_literal(item, depth + 1) for item in cast("list[Any]", value)]
        open_, close = "[", "]"
    else:
        items = cast("dict[str, Any]", value).items()
        parts = [f"{json.dumps(k)}: {_literal(v, depth + 1)}" for k, v in items]
        open_, close = "{", "}"
    if not parts:
        return open_ + close
    inline = f"{open_}{', '.join(parts)}{close}"
    if "\n" not in inline and depth * 4 + len(inline) <= WIDTH - 8:
        return inline
    indent = "    " * depth
    body = "".join(f"{indent}    {part},\n" for part in parts)
    return f"{open_}\n{body}{indent}{close}"


def _symbol(name: str, prefix: str) -> str:
    if not name.startswith(prefix):
        raise SystemExit(f"unexpected external type: {name}")
    return name[len(prefix) :].replace(".", "_")


def _constant(symbol: str) -> str:
    """``DescriptorProto_ExtensionRange`` to ``DESCRIPTOR_PROTO_EXTENSION_RANGE``."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", symbol)
    return snake.replace("__", "_").upper()


def _docstring(text: str, indent: str) -> str:
    lines = [line.removeprefix(" ").rstrip() for line in text.strip().split("\n")]
    escaped = [line.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') for line in lines]
    if len(escaped) == 1 and not escaped[0].endswith('"'):
        one = f'{indent}"""{escaped[0]}"""\n'
        if len(one) <= WIDTH + 1:
            return one
    body = "".join(f"{indent}{line}\n" if line else "\n" for line in escaped)
    return f'{indent}"""\n{body}{indent}"""\n'


class _Renderer:
    def __init__(self, file: Mapping[str, Any]) -> None:
        self.prefix = f".{file['package']}."
        info = file.get("source_code_info")
        if not info or not info.get("location"):
            raise SystemExit("descriptor source information is required")
        self.locations = {
            ".".join(str(p) for p in location.get("path", [])): location
            for location in info["location"]
        }
        self.classes: list[str] = []
        self.out: list[str] = []
        self.names: list[str] = []

    def comments(self, path: Sequence[int]) -> str:
        location = self.locations.get(".".join(str(p) for p in path), {})
        text = location.get("leading_comments") or location.get("trailing_comments") or ""
        return text.strip()

    def field_type(self, field: Mapping[str, Any]) -> str:
        type_name = field.get("type_name")
        if field["type"] == _TYPE_ENUM:
            type = "int"
        elif type_name is not None:
            type = _symbol(type_name, self.prefix)
        else:
            type = _SCALARS.get(field["type"], "")
            if not type:
                raise SystemExit(f"unsupported field type: {field['name']}")
        if field.get("label") == _LABEL_REPEATED:
            return f"list[{type}]"
        if field.get("label") == _LABEL_REQUIRED:
            return f"Required[{type}]"
        return type

    def enumeration(self, value: Mapping[str, Any], path: list[int], full_name: str) -> None:
        name = _symbol(full_name, self.prefix)
        self.names.append(name)
        doc = self.comments(path) or f"The values of ``{full_name[1:]}``."
        self.out.append(f"\n\nclass {name}(IntEnum):\n{_docstring(doc, '    ')}\n")
        for index, entry in enumerate(value["value"]):
            self.out.append(f"    {entry['name']} = {entry['number']}\n")
            comment = self.comments([*path, 2, index])
            if comment:
                self.out.append(_docstring(comment, "    "))

    def message(
        self, value: Mapping[str, Any], path: list[int], full_name: str, reference: str
    ) -> None:
        name = _symbol(full_name, self.prefix)
        if value.get("oneof_decl"):
            raise SystemExit("the renderer does not support oneofs")
        doc = self.comments(path) or f"The fields of ``{full_name[1:]}``."
        self.out.append(f"\n\nclass {name}(TypedDict, total=False):\n{_docstring(doc, '    ')}")
        fields = value.get("field", [])
        documented = True
        for index, field in enumerate(fields):
            if keyword.iskeyword(field["name"]):
                raise SystemExit(f"{full_name}: field {field['name']} is a Python keyword")
            enum = field["type"] == _TYPE_ENUM
            gap = "\n" if documented else ""
            self.out.append(f"{gap}    {field['name']}: {self.field_type(field)}\n")
            comment = self.comments([*path, 2, index])
            if enum:
                enum_name = _symbol(field["type_name"], self.prefix)
                note = f"A ``{enum_name}``."
                comment = f"{note}\n\n{comment}" if comment else note
            documented = bool(comment)
            if comment:
                self.out.append(_docstring(comment, "    "))
        constant = _constant(name)
        self.names += [name, constant]
        self.out.append(
            f"\n\n{constant}: MessageDescriptor = {reference}\n"
            f'"""The descriptor of ``{full_name[1:]}``."""\n'
        )
        for index, nested in enumerate(value.get("nested_type", [])):
            self.message(
                nested,
                [*path, 3, index],
                f"{full_name}.{nested['name']}",
                f"{constant}.messages[{index}]",
            )
        for index, nested in enumerate(value.get("enum_type", [])):
            self.enumeration(nested, [*path, 4, index], f"{full_name}.{nested['name']}")


HEADER = '''\
# @generated by scripts/gen_protobuf_descriptor.py. Do not edit.
# Source: protocolbuffers/protobuf v36.2 (2c74169b34066ceb8ddb6b882fcb3fb32d737a55).
# Regenerate: uv run python scripts/gen_protobuf_descriptor.py
"""The types and descriptors of Google's ``google/protobuf/descriptor.proto``
(Effect's ``protobuf/ProtobufDescriptorProto``): the messages that describe
protobuf files, messages, fields, enums and services.

Each message is a ``TypedDict`` of its fields and an upper-case constant,
its descriptor: ``FileDescriptorProto`` and ``FILE_DESCRIPTOR_PROTO``. An
enum field holds the number of a value of its ``IntEnum``. The definitions
and comments come from protobuf v36.2 (BSD-3-Clause; see
THIRD_PARTY_NOTICES.md).
"""

from __future__ import annotations

from enum import IntEnum
from typing import Required, TypedDict

from pyfect._public import publish
from pyfect.protobuf import _resolve
from pyfect.protobuf._descriptors import FileDescriptor, MessageDescriptor

'''


def generate(bootstrap: Path | None = None) -> str:
    data = FIXTURE.read_bytes()
    if hashlib.sha256(data).hexdigest() != FIXTURE_SHA256:
        raise SystemExit(f"unexpected input: {FIXTURE}")
    set_descriptor, file_descriptor = _descriptors(bootstrap)
    from pyfect.protobuf import _binary

    decoded = _binary.decode(set_descriptor, data)
    file = next(
        f
        for f in cast("list[dict[str, Any]]", decoded["file"])
        if f.get("name") == "google/protobuf/descriptor.proto"
    )
    renderer = _Renderer(file)
    compact = _compact(file, file_descriptor)
    compact.pop("source_code_info", None)
    out = [
        HEADER,
        f"DESCRIPTOR_FILE: FileDescriptor = _resolve.resolve([{_literal(compact)}]).files[0]\n",
        '"""The resolved ``google/protobuf/descriptor.proto``."""\n',
    ]
    for index, value in enumerate(file["message_type"]):
        renderer.message(
            value,
            [4, index],
            f"{renderer.prefix}{value['name']}",
            f"DESCRIPTOR_FILE.messages[{index}]",
        )
    for index, value in enumerate(file["enum_type"]):
        renderer.enumeration(value, [5, index], f"{renderer.prefix}{value['name']}")
    out += renderer.out
    names = sorted(["DESCRIPTOR_FILE", *renderer.names])
    out.append("\n\n__all__ = [\n" + "".join(f'    "{n}",\n' for n in names) + "]\n")
    out.append("\npublish(globals())\n")
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate pyfect.protobuf.descriptor_proto")
    parser.add_argument("--check", action="store_true", help="fail when the module is stale")
    parser.add_argument("--bootstrap", type=Path, default=None, help="a FileDescriptorProto JSON")
    args = parser.parse_args(argv)
    output = generate(args.bootstrap)
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != output:
            print(f"{TARGET.name} is stale; rerun {Path(__file__).name}", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
