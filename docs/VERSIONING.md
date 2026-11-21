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

## Adding an entry and cutting a release

An entry is a file of its own, `changes/<slug>.<section>.md`, where the section is `added`,
`changed`, `deprecated`, `removed`, `fixed`, `performance` or `docs`, and the body is the
entry's Markdown, starting with `- ` and with later lines indented two spaces. A branch adds
fragments and never edits CHANGELOG.md, so a release merged meanwhile can't take its entry.

`uv run python scripts/release.py 0.6.19` cuts a release: the fragments become
`## 0.6.19 (date)` in CHANGELOG.md, in the order Added, Changed, Deprecated, Removed, Fixed,
Performance, Docs, and are deleted; pyproject's version is set and `uv lock` run. It refuses a
patch version while a `changed` or `removed` fragment waits.

## Enforced

`tests/test_changelog.py` fails if:

- CHANGELOG.md changes other than in a release commit (one new section on top, for
  pyproject's version, with no fragment left), or has a heading that is not a version;
- a file in `changes/` is not a fragment, or two fragments cite the same Effect change;
- a patch section after 0.5.5 has a heading other than Fixed, Added, Deprecated, Performance
  or Docs;
- a `changed` or `removed` fragment is on main while pyproject's version is in the newest
  released minor series: the next release would have to be a minor one, so the change waits
  on a `-0X0` branch.

Releases up to 0.5.5 were made before this policy and are not checked.
