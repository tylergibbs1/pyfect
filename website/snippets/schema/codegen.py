from pyfect import codegen
from pyfect import schema as S
from pyfect.codegen import code, doc_comment, import_named, indent, join, literal
from pyfect.schema import representation as R

# Schemas as Python source: each becomes a variable of its name.
document = R.to_representations((S.String.check(S.is_min_length(3)), S.Int))
username, age = document.representations
schemas = codegen.Module().add_schemas(
    {"Username": username, "Age": age}, references=document.references
)
print(schemas.print())

# A module built from declarations: names are allocated, imports written when used.
module = codegen.Module()
dataclass = import_named("dataclasses", "dataclass")
point = module.declare("Point")
origin = module.declare("ORIGIN")
fields = join(["x: float", "y: float"], "\n")
module.define(
    point,
    [
        code(
            "@",
            dataclass,
            "\nclass ",
            point,
            ":",
            indent(code("\n", doc_comment("A point."), fields)),
        )
    ],
)
# ORIGIN calls Point when the module runs, so Point is written first.
module.define(
    origin, [code(origin, " = ", point, "(", literal(0.0), ", ", literal(0.0), ")")], [point]
)
source = module.print()
print(source)

namespace: dict[str, object] = {}
exec(source, namespace)
assert repr(namespace["ORIGIN"]) == "Point(x=0.0, y=0.0)"
