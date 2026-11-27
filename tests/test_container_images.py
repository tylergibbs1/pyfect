"""CI loads a job's container images before its tests start, and a test never loads or pulls one
there: an image the job did not load fails the test with the reason, instead of skipping it or
loading it while other tests run (tests/_container_images.py)."""

from pathlib import Path
from subprocess import CompletedProcess

import _container_images
import pytest
from oracle._shared_server import SharedServer


class _FakeDocker:
    """``docker``, recording each call: images in ``present`` exist, and a load of
    ``<key>.tar`` adds that image."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.present: set[str] = set()

    def __call__(self, *args: str, timeout: float = 900) -> CompletedProcess[str]:
        self.calls.append(args)
        if args[:2] == ("image", "inspect"):
            return CompletedProcess(args, 0 if args[2] in self.present else 1, "", "")
        if args[0] == "load":
            key = Path(args[-1]).stem
            self.present.add(_container_images.image(key).local)
        return CompletedProcess(args, 0, "", "")


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> _FakeDocker:
    fake = _FakeDocker()
    monkeypatch.setattr(_container_images, "_docker", fake)
    return fake


def test_a_test_never_loads_an_image_while_other_tests_run(
    monkeypatch: pytest.MonkeyPatch, docker: _FakeDocker
) -> None:
    """Run 45937052191: the tests loaded each image when a test first needed it, so GBs of
    image layers were written while other tests ran; a subprocess's imports waited on the disk
    and its test timed out. In a job that loaded its images, a missing one fails at once."""
    monkeypatch.setenv(_container_images.PRELOADED_ENV, "mysql redis")
    server = SharedServer[str]("SQL Server", "json", (RuntimeError, OSError))

    def start() -> str:
        return _container_images.ensure(_container_images.image("mssql"))

    with pytest.raises(_container_images.ImageUnavailable, match=r"mssql was not loaded"):
        server.get(start)
    with pytest.raises(pytest.fail.Exception, match="mssql was not loaded"):
        server.get(start)
    assert docker.calls == []


def test_a_test_runs_an_image_the_job_loaded(
    monkeypatch: pytest.MonkeyPatch, docker: _FakeDocker
) -> None:
    monkeypatch.setenv(_container_images.PRELOADED_ENV, "all")
    mysql = _container_images.image("mysql")
    assert _container_images.ensure(mysql) == mysql.local
    assert docker.calls == []


def test_load_loads_the_named_images_and_checks_each(tmp_path: Path, docker: _FakeDocker) -> None:
    for key in ("mysql", "busybox"):
        (tmp_path / f"{key}.tar").write_bytes(b"")
    _container_images.load(tmp_path, "mysql busybox")
    loads = [call for call in docker.calls if call[0] == "load"]
    assert loads == [
        ("load", "-q", "-i", str(tmp_path / "mysql.tar")),
        ("load", "-q", "-i", str(tmp_path / "busybox.tar")),
    ]
    assert docker.present == {
        _container_images.image("mysql").local,
        _container_images.image("busybox").local,
    }


def test_load_all_loads_every_cached_image(tmp_path: Path, docker: _FakeDocker) -> None:
    for found in _container_images.cached():
        (tmp_path / f"{found.key}.tar").write_bytes(b"")
    _container_images.load(tmp_path, "all")
    assert docker.present == {found.local for found in _container_images.cached()}


def test_load_ends_the_run_on_a_missing_archive_or_an_unknown_image(
    tmp_path: Path, docker: _FakeDocker
) -> None:
    with pytest.raises(SystemExit, match=r"image load failed: .*mssql\.tar is missing"):
        _container_images.load(tmp_path, "mssql")
    with pytest.raises(SystemExit, match=r"unknown image 'postgres'"):
        _container_images.load(tmp_path, "postgres")
    with pytest.raises(SystemExit, match=r"no images named"):
        _container_images.load(tmp_path, " ")
    assert docker.calls == []


def test_an_image_runs_under_a_tag_naming_its_pinned_digest() -> None:
    mssql = _container_images.image("mssql")
    assert mssql.pinned == f"mcr.microsoft.com/mssql/server@{mssql.digest}"
    assert mssql.local == f"pyfect-test/mssql:{mssql.digest.removeprefix('sha256:')[:16]}"
    assert _container_images.image("busybox").pinned.startswith("busybox@sha256:")
