# Typing experiments

Each file checks one question against pyright. Run one with
`uv run pyright research/typing/<file>`. They are excluded from the normal
checks; the decisions they led to are pinned by `tests/type_checks.py`.

| File | Question | Answer |
| --- | --- | --- |
| `exp1_tags.py` | Can a tag's identity differ from its shape, with R tracking the tag? | Yes, with `class Primary(Tag[Db])`. A bare class can't be yielded (`yield from Primary`) through a metaclass. |
| `exp2_provide.py` | Can `provide` remove only what a layer builds, leaving the rest of R? | Yes, if the layer is known before the effect: `provide(layer)(eff)`. |
| `exp3_methods.py` | Can `catch_tag` / `provide` be methods? | No. `self` binds first, and `catch_tag` then silently erases *all* errors. Unsound. |
| `exp4_pipe.py`, `exp5_pipe_overloads.py` | Do those work in a multi-step `pipe(a, b)`? | Only the first step narrows; later ones keep the type unchanged. One step per `.pipe()` is exact, so `pipe` takes one function. An exact-match overload is needed so a full match gives `Never`. |
| `exp6_strict.py` | What does strict mode say about unannotated effect generators? | Only that the generator's send type is `Unknown` (pyright #10279). `reportUnknownParameterType = false` silences it; parameters are still required to be annotated. |
| `exp7_layers.py`, `exp8_fixes.py` | Can `layer.succeed(Tag, impl)` check `impl`? Does `E1 \| E2` stay precise? | Recover shape and tag through a protocol on the tag class; make the shape invariant or wrong impls are accepted. Two separate `Never`-defaulted TypeVars in a union become `Unknown`; one shared TypeVar across arguments joins correctly. |
| `exp9_methods_union.py` | Do `flat_map`-style methods hit the same `Unknown`? | Not when they use the class's own TypeVars. Rebinding `self` to fresh TypeVars locks them and rejects valid code. |
