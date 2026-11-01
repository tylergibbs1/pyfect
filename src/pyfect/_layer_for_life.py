"""``make(..., layer=...)``: a value made with a layer that lives as long as
the value does.

``made.pipe(provide(layer))`` releases the layer once ``made`` returns, so a
client made that way outlives its protocol or handlers. ``with_layer(make,
layer)`` builds ``layer`` into the caller's ``Scope`` instead, the scope the
value is valid in, and is what every ``layer=`` parameter uses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect
from pyfect._layer_core import Layer, require_layer
from pyfect.effect import provide_context


def with_layer(
    make: Callable[[], Effect[Any, Any, Any]], layer: Layer[Any, Any, Any] | None
) -> Effect[Any, Any, Any]:
    """``make()``, with the services of ``layer`` built into the caller's
    ``Scope`` (``layer`` is checked first); without ``layer``, ``make()``
    alone."""
    if layer is None:
        return make()
    require_layer(layer, "layer")
    made = make()
    return layer.build().flat_map(lambda built: made.pipe(provide_context(built)))


__all__ = ["with_layer"]
