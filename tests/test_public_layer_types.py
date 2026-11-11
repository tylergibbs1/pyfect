"""No public function erases a layer's requirements with ``Any``.

A ``Layer[..., Any]`` parameter accepts a layer whatever it still needs, and a
``Layer[Any, Any, Any]`` result drops what it needs, so a missing service becomes
a runtime failure instead of a pyright error: ``router.to_asgi`` took any routes
layer and served a 500 for every request needing a service nobody built, and
``router.provide_request`` returned ``Layer[Any, Any, Any]`` (graft #13, #14).
Implementations behind ``@overload`` may use ``Any``; the overloads may not."""

import inspect
import re
import typing
from collections.abc import Iterator

from _pyfect_modules import modules

# The requirements slot (the third argument) of a `Layer[...]` written as `Any`.
_ERASED_REQUIREMENTS = re.compile(r"Layer\[[^\[\]]*(\[[^\[\]]*\])?[^\[\]]*,\s*Any\]")
_ERASED_RESULT = re.compile(r"Layer\[Any, Any, Any\]")


def _public_functions() -> Iterator[tuple[str, typing.Callable[..., object]]]:
    seen: set[object] = set()
    for module in modules(public=True, skip_missing_extras=True):
        for name in getattr(module, "__all__", ()):
            value = getattr(module, name, None)
            if inspect.isfunction(value) and value not in seen:
                seen.add(value)
                yield f"{module.__name__}.{name}", value


def test_no_public_signature_erases_layer_requirements() -> None:
    erased: list[str] = []
    for name, function in _public_functions():
        for signature in typing.get_overloads(function) or [function]:
            for parameter, annotation in signature.__annotations__.items():
                text = str(annotation)
                if _ERASED_REQUIREMENTS.search(text) or _ERASED_RESULT.search(text):
                    erased.append(f"{name} ({parameter}: {text})")
    assert erased == []
