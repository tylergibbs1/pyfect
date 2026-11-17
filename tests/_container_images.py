"""The container images the server-backed tests run, pinned by digest in container_images.json.

The tests and ci.yml both read that file, so what CI caches is what the tests run. Each image
runs under a local tag naming its digest (``pyfect-test/mysql:<digest>``). Locally the first
test that needs one pulls it by digest and tags it. In CI, ci.yml's ``images`` job pulls each
image once, saves it with ``save``, and caches the archives under a key made from
container_images.json. The shards restore that cache and set ``PYFECT_IMAGE_ARCHIVES``: a test
then loads its image from there and never pulls. An image it can't load raises
``ImageUnavailable``, which fails the test instead of skipping it.

Usage (ci.yml): ``python3 tests/_container_images.py save DIR``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PINS = Path(__file__).with_name("container_images.json")
ARCHIVES_ENV = "PYFECT_IMAGE_ARCHIVES"
"""Where CI put the saved images; when set, a test loads its image and never pulls."""


class ImageUnavailable(Exception):
    """A run that preloads its images is missing one. Not a ``RuntimeError``, so the shared
    server fixtures fail the test with this reason instead of skipping it."""


@dataclass(frozen=True)
class Image:
    key: str
    ref: str
    digest: str
    arm_only: str | None = None
    """Why the image is only run on ARM hosts; CI (x86) neither caches nor runs it."""

    @property
    def pinned(self) -> str:
        """The image by digest: what is pulled."""
        name, _, tag = self.ref.rpartition(":")
        return f"{name if name and '/' not in tag else self.ref}@{self.digest}"

    @property
    def local(self) -> str:
        """The tag a test runs, naming the digest it was pulled at."""
        return f"pyfect-test/{self.key}:{self.digest.removeprefix('sha256:')[:16]}"


def _load_pins() -> dict[str, Image]:
    raw: dict[str, dict[str, str]] = json.loads(PINS.read_text(encoding="utf-8"))
    return {key: Image(key, **fields) for key, fields in raw.items()}


IMAGES = _load_pins()


def image(key: str) -> Image:
    return IMAGES[key]


def cached() -> list[Image]:
    """The images CI saves and preloads: every one but the ARM-only ones."""
    return [found for found in IMAGES.values() if found.arm_only is None]


def _docker(*args: str, timeout: float = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=timeout
    )


def _present(tag: str) -> bool:
    return _docker("image", "inspect", tag, timeout=60).returncode == 0


def ensure(found: Image) -> str:
    """``found``'s local tag, loaded from CI's archives or pulled by digest if not there yet.
    Locally a failed pull raises ``RuntimeError`` (the test skips, as without Docker); with
    ``PYFECT_IMAGE_ARCHIVES`` set, a missing or unloadable image raises ``ImageUnavailable``."""
    if _present(found.local):
        return found.local
    archives = os.environ.get(ARCHIVES_ENV)
    if archives:
        archive = Path(archives) / f"{found.key}.tar"
        if not archive.is_file():
            raise ImageUnavailable(
                f"image load failed: {archive} is missing; ci.yml's images job saves every "
                "image in tests/container_images.json"
            )
        loaded = _docker("load", "-q", "-i", str(archive))
        if loaded.returncode != 0 or not _present(found.local):
            raise ImageUnavailable(
                f"image load failed: {archive} did not give {found.local}: "
                f"{loaded.stderr.strip() or loaded.stdout.strip()}"
            )
        return found.local
    pulled = _docker("pull", found.pinned)
    if pulled.returncode != 0:
        raise RuntimeError(f"cannot pull {found.pinned}: {pulled.stderr.strip()}")
    _docker("tag", found.pinned, found.local, timeout=60)
    return found.local


def save(directory: Path) -> None:
    """Pull every cached image once, by digest, and save it under its local tag to
    ``directory/<key>.tar``. A failed pull or save ends the run with the reason; nothing is
    retried."""
    directory.mkdir(parents=True, exist_ok=True)
    for found in cached():
        pulled = _docker("pull", found.pinned)
        if pulled.returncode != 0:
            sys.exit(f"image pull failed: {found.pinned}: {pulled.stderr.strip()}")
        tagged = _docker("tag", found.pinned, found.local, timeout=60)
        saved = _docker("save", "-o", str(directory / f"{found.key}.tar"), found.local)
        if tagged.returncode != 0 or saved.returncode != 0:
            sys.exit(f"image save failed: {found.local}: {(tagged.stderr + saved.stderr).strip()}")
        print(f"saved {found.local} ({found.pinned})")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "save":
        sys.exit("usage: _container_images.py save DIR")
    save(Path(sys.argv[2]))
