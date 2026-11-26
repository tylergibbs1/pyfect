- `codegen.Module.print` lays out a module of schemas alone as Effect's `Codegen` does, and as a
  module mixing schemas and declarations already did: each schema's `type` alias just before its
  value, and the imports in the order the schemas use them, `from pyfect import schema as S`
  first. 0.6 put every type alias first and imported `typing` before `pyfect`. The generated code
  means the same; to migrate, regenerate checked-in generated modules and commit them.
