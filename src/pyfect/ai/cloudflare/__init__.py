"""Cloudflare Workers AI for ``pyfect.ai`` (Effect's ``@effect/ai-cloudflare``):
the ``client`` for Clef decisions, the ``decision_model`` over it and the
wire ``schema``. Requests go over the ``HttpClient`` service::

    from pyfect.ai.cloudflare import client, decision_model

    program.pipe(fx.provide(decision_model.model("clef-flash").layer)).pipe(
        fx.provide(client.layer_config())
    )
"""

from pyfect.ai.cloudflare import client, decision_model, schema
from pyfect.ai.cloudflare.client import CloudflareClient

__all__ = ["CloudflareClient", "client", "decision_model", "schema"]
