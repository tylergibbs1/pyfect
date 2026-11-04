"""TypeSafe for ``pyfect.ai`` (Effect's ``@effect/ai-typesafe``): the
``client`` for System One decisions and the model list, its per-call
``config``, the ``decision_model`` over it and the wire ``schema``.
Requests go over the ``HttpClient`` service::

    from pyfect.ai.typesafe import client, decision_model

    program.pipe(fx.provide(decision_model.model("jev-latest").layer)).pipe(
        fx.provide(client.layer_config())
    )
"""

from pyfect.ai.typesafe import client, config, decision_model, schema
from pyfect.ai.typesafe.client import TypeSafeClient
from pyfect.ai.typesafe.config import TypeSafeConfig

__all__ = ["TypeSafeClient", "TypeSafeConfig", "client", "config", "decision_model", "schema"]
