"""The ``effect/encoding`` modules no other cluster lists: Toml, and the larger
ones not ported yet (see "Still open" in docs/PARITY.md)."""

from api_coverage import Cluster, Module

ISINSTANCE = "`TypeId` symbols and `is*` guards"

TOML = Module("Toml", "effect/src/encoding/Toml.ts", ("pyfect.encoding.toml",))
XML = Module("Xml", "effect/src/encoding/Xml.ts", ("pyfect.encoding",))
TAR = Module("Tar", "effect/src/encoding/Tar.ts", ("pyfect.encoding",))
ZIP = Module("Zip", "effect/src/encoding/Zip.ts", ("pyfect.encoding",))
SCHEMA_BINARY = Module("SchemaBinary", "effect/src/encoding/SchemaBinary.ts", ("pyfect.encoding",))

CLUSTER = Cluster(
    "encoding",
    "Effect's encoding modules outside the other clusters",
    (TOML, XML, TAR, ZIP, SCHEMA_BINARY),
)
