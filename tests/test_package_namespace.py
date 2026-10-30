"""``import pyfect.X`` then ``pyfect.X.name`` must reach the submodule: a
package attribute of the same name (``fx.context``, the effect) would
shadow it at runtime while pyright, which resolves the submodule, says the
code is fine."""

import pkgutil
import subprocess
import sys
import types

import pyfect
import pyfect as fx


def test_every_public_submodule_is_reachable_as_a_package_attribute():
    shadowed = [
        info.name
        for info in pkgutil.iter_modules(pyfect.__path__)
        if hasattr(pyfect, info.name)
        and not isinstance(getattr(pyfect, info.name), types.ModuleType)
    ]
    assert shadowed == []


def test_import_pyfect_context_reaches_the_context_module():
    program = "import pyfect.context\nclass Db(pyfect.context.Tag[str]): ...\nprint(Db.key)\n"
    run = subprocess.run(
        [sys.executable, "-I", "-c", program], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr


def test_fx_context_is_still_the_effect_of_the_current_services():
    class Db(fx.Tag[str]): ...

    services = fx.run_sync(fx.context(Db).pipe(fx.provide_service(Db, "db")))
    assert services.get(Db) == "db"


def test_import_pyfect_loads_the_platform_subpackages_only_when_used():
    program = (
        "import sys, pyfect as fx\n"
        "heavy = ('pyfect.ai', 'pyfect.http', 'pyfect.cli', 'pyfect.graphql', 'pyfect.sql')\n"
        "print(sorted(m for m in heavy if m in sys.modules))\n"
        "fx.ai\n"
        "print('pyfect.ai' in sys.modules)\n"
    )
    run = subprocess.run(
        [sys.executable, "-I", "-c", program], capture_output=True, text=True, check=True
    )
    assert run.stdout.splitlines() == ["[]", "True"]


def test_an_unknown_attribute_is_still_an_attribute_error():
    import pytest

    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        getattr(fx, "nope")  # noqa: B009
