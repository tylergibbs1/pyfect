"""The container images the server-backed tests run, pinned by digest in container_images.json.

The tests and ci.yml both read that file, so what CI caches is what the tests run. Each image
runs under a local tag naming its digest (``pyfect-test/mysql:<digest>``). Locally the first
test that needs one pulls it by digest and tags it. In CI, ci.yml's ``images`` job pulls each
image once, saves it with ``save``, and caches the archives under a key made from
container_images.json. A job that runs server tests restores that cache and loads the images it
names with ``load`` before its tests start, then sets ``PYFECT_IMAGES_PRELOADED``: a test there
never loads or pulls an image (loading one wrote GBs to the disk the other tests were reading,
run 45937052191). An image the job did not load raises ``ImageUnavailable``, which fails the test
instead of skipping it.

Usage (.github/actions/container-images): ``python3 tests/_container_images.py save DIR`` and
``python3 tests/_container_images.py load DIR IMAGES`` (``all`` or keys, space-separated).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PINS = Path(__file__).with_name("container_images.json")
PRELOADED_ENV = "PYFECT_IMAGES_PRELOADED"
"""The images the job loaded before its tests (``load``'s ``IMAGES``); when set, a test never
loads or pulls one."""


class ImageUnavailable(Exception):
    """A job that preloads its images did not load one. Not a ``RuntimeError``, so the shared
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


def named(images: str) -> list[Image]:
    """The images ``images`` names: ``all`` (every cached one) or keys, space-separated. An
    unknown key or no key at all ends the run with the reason."""
    keys = images.split()
    if keys == ["all"]:
        return cached()
    if not keys:
        sys.exit("no images named: give `all` or keys from tests/container_images.json")
    unknown = [key for key in keys if key not in IMAGES or IMAGES[key].arm_only]
    if unknown:
        sys.exit(f"unknown image {unknown[0]!r}: CI caches {sorted(i.key for i in cached())}")
    return [IMAGES[key] for key in keys]


def _docker(*args: str, timeout: float = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=timeout
    )


def _present(tag: str) -> bool:
    return _docker("image", "inspect", tag, timeout=60).returncode == 0


def ensure(found: Image) -> str:
    """``found``'s local tag, pulled by digest if not there yet. Locally a failed pull raises
    ``RuntimeError`` (the test skips, as without Docker). In a job that loaded its images
    (``PYFECT_IMAGES_PRELOADED``), one it did not load raises ``ImageUnavailable``."""
    preloaded = os.environ.get(PRELOADED_ENV)
    if preloaded is not None:
        if found not in named(preloaded):
            raise ImageUnavailable(
                f"{found.key} was not loaded before the tests: name it in the job's "
                "`images` input of .github/actions/container-images"
            )
        return found.local
    if _present(found.local):
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


def load(directory: Path, images: str) -> None:
    """Load the images ``images`` names from ``directory/<key>.tar``, then wait until the
    disk has written them (``sync``), so no test runs while it does. A missing archive or a
    failed load ends the run with the reason; nothing is retried."""
    for found in named(images):
        archive = directory / f"{found.key}.tar"
        if not archive.is_file():
            sys.exit(f"image load failed: {archive} is missing; the images job saves it")
        loaded = _docker("load", "-q", "-i", str(archive))
        if loaded.returncode != 0 or not _present(found.local):
            sys.exit(
                f"image load failed: {archive} did not give {found.local}: "
                f"{loaded.stderr.strip() or loaded.stdout.strip()}"
            )
        print(f"loaded {found.local}")  # the job log times each line
    os.sync()
    print("synced the disk")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "save":
        save(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == "load":
        load(Path(sys.argv[2]), sys.argv[3])
    else:
        sys.exit("usage: _container_images.py save DIR | load DIR IMAGES")
