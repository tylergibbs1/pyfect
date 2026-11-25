"""The sitemap dates each guide from `website/lib/page-dates.json`, which
`website/scripts/page_dates.py` keeps: an edit to a guide, a snippet it includes or a diagram
it draws must come with a refreshed file, or the sitemap would keep the old date.

The dates were once read from git history at build time, but Vercel's clone has none, so the
live sitemap had no dates for any guide and nothing failed.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "website" / "scripts" / "page_dates.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("page_dates", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


page_dates = _script()


def test_every_guide_is_dated_and_no_date_is_stale(capsys: pytest.CaptureFixture[str]):
    code = page_dates.main(["--check"])
    assert code == 0, capsys.readouterr().err


def _site(root: Path) -> Path:
    (root / "content" / "docs" / "reference").mkdir(parents=True)
    (root / "snippets").mkdir()
    (root / "diagrams").mkdir()
    (root / "lib").mkdir()
    (root / "snippets" / "a.py").write_text("x = 1\n")
    (root / "diagrams" / "flow.mmd").write_text("graph LR; a-->b\n")
    (root / "content" / "docs" / "index.mdx").write_text("# Home\n")
    (root / "content" / "docs" / "guide.mdx").write_text(
        '<include>../../snippets/a.py</include>\n<Diagram name="flow" title="t" />\n'
    )
    (root / "content" / "docs" / "reference" / "skipped.mdx").write_text("# generated\n")
    return root


def test_a_guide_is_redated_when_it_or_what_it_shows_changes(tmp_path: Path):
    site = _site(tmp_path)
    first = page_dates.refreshed(site, {}, "2026-01-01")
    assert sorted(first) == ["", "guide"]  # reference pages are not guides

    assert page_dates.refreshed(site, first, "2026-02-01") == first

    (site / "snippets" / "a.py").write_text("x = 2\n")
    after_snippet = page_dates.refreshed(site, first, "2026-03-01")
    assert after_snippet["guide"]["date"] == "2026-03-01"
    assert after_snippet[""] == first[""]

    (site / "diagrams" / "flow.mmd").write_text("graph LR; a-->c\n")
    assert page_dates.refreshed(site, after_snippet, "2026-04-01")["guide"]["date"] == "2026-04-01"


def test_check_fails_on_a_stale_file_and_names_the_guide(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    site = _site(tmp_path)
    assert page_dates.main([], site) == 0
    assert page_dates.main(["--check"], site) == 0

    (site / "content" / "docs" / "guide.mdx").write_text("changed\n")
    assert page_dates.main(["--check"], site) == 1
    assert "guide" in capsys.readouterr().err

    (site / "content" / "docs" / "guide.mdx").unlink()
    page_dates.main([], site)
    assert sorted(json.loads((site / "lib" / "page-dates.json").read_text())) == [""]
