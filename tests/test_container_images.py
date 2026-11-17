"""A run that preloads its container images fails a test whose image it cannot load, with the
reason; it never skips it or pulls instead (tests/_container_images.py)."""

from pathlib import Path

import _container_images
import pytest
from oracle._shared_server import SharedServer


def test_a_missing_archive_fails_the_test_instead_of_skipping_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(_container_images.ARCHIVES_ENV, str(tmp_path))

    def absent(_tag: str) -> bool:
        return False

    monkeypatch.setattr(_container_images, "_present", absent)
    server = SharedServer[str]("SQL Server", "json", (RuntimeError, OSError))

    def start() -> str:
        return _container_images.ensure(_container_images.image("mssql"))

    with pytest.raises(
        _container_images.ImageUnavailable, match=r"image load failed: .*mssql\.tar"
    ):
        server.get(start)
    with pytest.raises(pytest.fail.Exception, match="image load failed"):
        server.get(start)


def test_an_image_runs_under_a_tag_naming_its_pinned_digest() -> None:
    mssql = _container_images.image("mssql")
    assert mssql.pinned == f"mcr.microsoft.com/mssql/server@{mssql.digest}"
    assert mssql.local == f"pyfect-test/mssql:{mssql.digest.removeprefix('sha256:')[:16]}"
    assert _container_images.image("busybox").pinned.startswith("busybox@sha256:")
