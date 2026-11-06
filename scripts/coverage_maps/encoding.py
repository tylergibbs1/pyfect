"""The ``effect/encoding`` modules no other cluster lists."""

from api_coverage import Cluster, Module

ISINSTANCE = "`TypeId` symbols and `is*` guards"

TOML = Module("Toml", "effect/src/encoding/Toml.ts", ("pyfect.encoding.toml",))
XML = Module("Xml", "effect/src/encoding/Xml.ts", ("pyfect.encoding.xml",))
TAR = Module("Tar", "effect/src/encoding/Tar.ts", ("pyfect.encoding.tar",))
ZIP = Module("Zip", "effect/src/encoding/Zip.ts", ("pyfect.encoding.zip",))
SCHEMA_BINARY = Module(
    "SchemaBinary", "effect/src/encoding/SchemaBinary.ts", ("pyfect.encoding.schema_binary",)
)

CLUSTER = Cluster(
    "encoding",
    "Effect's encoding modules outside the other clusters",
    (TOML, XML, TAR, ZIP, SCHEMA_BINARY),
)
