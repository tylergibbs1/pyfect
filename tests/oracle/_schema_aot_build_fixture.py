"""The module ``SchemaAOTCompilerBuild`` compiles (Effect's
``fixtures/aot-build.ts``)."""

from __future__ import annotations

import pyfect.schema as S

from ._schema_binary import struct

Port = S.NumberFromString

User = struct(name=S.String, port=Port)

ignored = "not a Schema"
