"""One layer under ``test_layer_reuse``."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect import layer as L

type AnyLayer = fx.Layer[Any, Any, Any]
type AnyEffect = fx.Effect[Any, Any, Any]


@dataclass(frozen=True)
class Case:
    """``layer()`` makes the one layer value given to every run. Each run
    provides it with ``needs()`` (made afresh for that run, and visible to
    ``use``) and runs ``use()``, which goes through the layer's services
    the way an app would. A layer that a run cannot simply provide (one a
    worker thread runs, say) gives ``run(value)``, the whole program of a
    run, instead of ``needs`` and ``use``."""

    layer: Callable[[], AnyLayer]
    needs: Callable[[], AnyLayer] | None = None
    use: Callable[[], AnyEffect] = field(default=lambda: fx.void)
    run: Callable[[AnyLayer], AnyEffect] | None = None
    timeout: float = 15
    concurrent: bool = True
    """Whether two runs can share the value at once (not when it names a
    fixed port, say)."""

    def program(self, value: AnyLayer) -> AnyEffect:
        """One run's program, over the shared layer value."""
        if self.run is not None:
            return self.run(value)
        provided = value if self.needs is None else value.pipe(L.provide_merge(self.needs()))
        return self.use().pipe(fx.provide(provided))
