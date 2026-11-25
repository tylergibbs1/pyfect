"""Python modules built from bindings and code fragments (Effect's ``Codegen``).

``Module`` either collects named schemas (``add_schemas``) and prints them as one
module, which replaces ``representation.to_code_document`` followed by
``to_code_module``, or builds a module from declarations: ``declare`` allocates a
name, ``define`` gives it source made with ``code``, ``join``, ``indent`` and
``literal``, and the bindings of ``import_namespace`` / ``import_named`` become
import statements when used. Names are allocated so nothing shadows a keyword, a
builtin, a reserved name or another declaration; strings are written unchanged.

Python spellings of Effect's: ES namespace and named imports are ``import m as X``
and ``from m import x``, a type-only import goes under ``if TYPE_CHECKING:``,
``indent`` indents by four spaces, ``literal`` writes Python literals and
``doc_comment`` a docstring. Python has no default export, import attributes or
object-literal keys, so ``importDefault``, ``attributes`` and ``propertyKey`` have no
counterpart."""

from __future__ import annotations

from pyfect.codegen._fragment import (
    Binding,
    CodeHole,
    DeclarationBinding,
    Fragment,
    Render,
    code,
    deferred,
    doc_comment,
    indent,
    join,
    literal,
)
from pyfect.codegen._imports import (
    Import,
    NamedImport,
    NamespaceImport,
    import_named,
    import_namespace,
)
from pyfect.codegen._module import Finalized, FinalizedDeclaration, Module
from pyfect.codegen._names import Scope

__all__ = [
    "Binding",
    "CodeHole",
    "DeclarationBinding",
    "Finalized",
    "FinalizedDeclaration",
    "Fragment",
    "Import",
    "Module",
    "NamedImport",
    "NamespaceImport",
    "Render",
    "Scope",
    "code",
    "deferred",
    "doc_comment",
    "import_named",
    "import_namespace",
    "indent",
    "join",
    "literal",
]
