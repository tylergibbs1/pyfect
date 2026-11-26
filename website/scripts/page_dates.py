"""Write `website/lib/page-dates.json`: the day each guide last changed, for the sitemap.

A guide is its `.mdx` file plus the snippets it includes and the diagrams it draws. Each entry
holds the SHA-256 of those files and the day (UTC) the hash last changed: refreshing gives a
guide whose content changed, or a new guide, today's date and drops guides that are gone.
`app/sitemap.ts` reads the file, so the dates need no git history at build time (Vercel's
clone has none). `--check` writes nothing and exits 1 when the file is stale;
`tests/test_page_dates.py` runs it.

    uv run python website/scripts/page_dates.py [--check]
"""

import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

WEBSITE = Path(__file__).resolve().parent.parent
DATES = "lib/page-dates.json"

INCLUDE = re.compile(r"<include[^>]*>([^<]+)</include>")
DIAGRAM = re.compile(r"<Diagram\s[^>]*\bname=\"([^\"]+)\"")

type Dates = dict[str, dict[str, str]]


def slug(website: Path, guide: Path) -> str:
    """The guide's path under `/docs`: `schema`, or `` for the index."""
    path = guide.relative_to(website / "content" / "docs").with_suffix("").as_posix()
    return "" if path == "index" else path.removesuffix("/index")


def sources(website: Path, guide: Path) -> list[Path]:
    """The files whose content the guide's page shows."""
    text = guide.read_text(encoding="utf-8")
    included = [(guide.parent / name.strip()).resolve() for name in INCLUDE.findall(text)]
    drawn = [website / "diagrams" / f"{name}.mmd" for name in DIAGRAM.findall(text)]
    return [guide, *included, *drawn]


def content_hash(website: Path, guide: Path) -> str:
    digest = hashlib.sha256()
    for source in sources(website, guide):
        digest.update(source.relative_to(website).as_posix().encode())
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def guides(website: Path) -> list[Path]:
    docs = website / "content" / "docs"
    return sorted(
        path for path in docs.rglob("*.mdx") if "reference" not in path.relative_to(docs).parts
    )


def read(website: Path) -> Dates:
    path = website / DATES
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def refreshed(website: Path, dates: Dates, today: str) -> Dates:
    """`dates` with each guide's entry brought up to date: a guide whose content changed
    since its entry was written, or a new guide, is dated `today`."""
    website = website.resolve()
    out: Dates = {}
    for guide in guides(website):
        key, sha = slug(website, guide), content_hash(website, guide)
        old = dates.get(key)
        out[key] = (
            old if old is not None and old["sha256"] == sha else {"date": today, "sha256": sha}
        )
    return out


def render(dates: Dates) -> str:
    return json.dumps(dates, indent=2, sort_keys=True) + "\n"


def main(argv: list[str], website: Path = WEBSITE) -> int:
    today = dt.datetime.now(dt.UTC).date().isoformat()
    dates = read(website)
    new = refreshed(website, dates, today)
    if "--check" in argv:
        if new == dates:
            return 0
        changed = sorted(
            key or "index" for key in new.keys() | dates.keys() if new.get(key) != dates.get(key)
        )
        print(
            f"website/lib/page-dates.json is stale for: {', '.join(changed)}.\n"
            "Run `uv run python website/scripts/page_dates.py` and commit the file.",
            file=sys.stderr,
        )
        return 1
    (website / DATES).write_text(render(new), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
