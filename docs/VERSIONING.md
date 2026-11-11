# Versioning

pyfect is before 1.0, so the minor number is the breaking one: `0.6.0` may break code that
worked on `0.5.x`, and `0.5.x` releases may not.

## A patch release (`0.5.6`) may contain

- **Fixed**: bugs. A fix may change behaviour only where the old behaviour was wrong and code
  could not sensibly rely on it: a crash, a leak, a wrong result, a hang.
- **Added**: new modules, functions, options and overloads that leave existing calls
  unchanged. Types that accept more correct code than before count as added.
- **Deprecated**: an old name keeps working and warns (`warnings.deprecated`, so pyright
  reports calls too), naming what to use instead and the minor release that removes it.
- **Performance**: faster or smaller with the same results.
- **Docs**.

## Only a minor release (`0.6.0`) may contain

- **Changed**: behaviour a working program could depend on, even when the change makes pyfect
  match Effect (a missing route answering a defect instead of a 404, for example).
- **Removed**: deprecated names, at least one minor release after they started warning.
- Stricter types that reject code pyright accepted before, even when that code was wrong at
  runtime.

Each entry under Changed or Removed says what to do instead.

## Enforced

`tests/test_changelog.py` fails if a patch section after 0.5.5 has a heading other than
Fixed, Added, Deprecated, Performance or Docs. The unreleased section counts: once it has a
Changed or Removed entry, the next release must be a minor one. Releases up to 0.5.5 were
made before this policy and are not checked.
