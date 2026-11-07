import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

from pyfect import schema as S
from pyfect.schema import aot_compiler, jit_compiler


class Order(TypedDict):
    id: int
    sku: str
    quantity: int


OrderSchema = S.Struct(Order)

# JIT: generate and compile Python source for this AST (and the nodes its
# parsers reach) on first use. Results are the interpreter's.
jit_compiler.enable(OrderSchema.ast)
decode = S.decode_unknown_sync(OrderSchema)
print(decode({"id": 1, "sku": "apple", "quantity": 2, "note": "dropped"}))
try:
    decode({"id": 1, "sku": "apple", "quantity": "2"})
except S.SchemaError as error:
    print(error.message)

# AOT: write the generated decoders as a module, import it, install them.
source = aot_compiler.compile([aot_compiler.Target(OrderSchema.ast, ["decode", "is"])])
path = Path(tempfile.mkdtemp()) / "order_decoders.py"
path.write_text(source)
spec = importlib.util.spec_from_file_location("order_decoders", path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules["order_decoders"] = module
spec.loader.exec_module(module)
module.install([OrderSchema.ast])
assert S.is_(OrderSchema)({"id": 2, "sku": "pear", "quantity": 1})
