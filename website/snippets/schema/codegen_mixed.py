from pyfect import codegen
from pyfect import schema as S
from pyfect.codegen import code
from pyfect.schema import representation as R

module = codegen.Module()
document = R.to_representation(S.String)
schemas = module.add_schemas({"User": document.representation}, references=document.references)
user = schemas["User"]
# "User" is the schema's, so this declaration is User1.
alias = module.declare("User")
source = module.define(alias, [code(alias, " = ", user)], [user]).print()
print(source)

assert "User1 = User" in source
