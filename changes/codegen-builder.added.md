- `pyfect.codegen` gains Effect 4.1.5's `Codegen` builder, writing Python: `Module.declare`,
  `define`, `scope`, `add_import`, `provide_import`, `add_side_effect`, `add` and `finalize`
  (and `print` for a module built from declarations), with `code`, `join`, `deferred`,
  `indent`, `literal`, `doc_comment`, `import_namespace` and `import_named`. A namespace import
  is `import m as X`, a named one `from m import x`, and a type-only one goes under
  `if TYPE_CHECKING:`. `importDefault` and `propertyKey` have no Python form; a module holds
  schemas or declarations, not both.
