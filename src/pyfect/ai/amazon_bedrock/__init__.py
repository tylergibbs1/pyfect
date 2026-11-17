"""Amazon Bedrock's Converse API for ``pyfect.ai`` (Effect's
``@effect/ai-amazon-bedrock``): the ``client``, its per-call ``config``, the
``language_model`` and the wire ``schema``. Requests go over the
``HttpClient`` service, signed with AWS Signature Version 4 on the
``Digest`` and ``Mac`` services (or sent with a Bedrock API key); streams
are read in the AWS event-stream framing::

    from pyfect.ai.amazon_bedrock import client, language_model
    from pyfect.crypto import native

    program.pipe(fx.provide(language_model.model(model_id).layer)).pipe(
        fx.provide(client.layer_config().pipe(fx.layer.provide(native.layer)))
    )
"""

from pyfect.ai.amazon_bedrock import client, config, language_model, schema
from pyfect.ai.amazon_bedrock.client import AmazonBedrockClient
from pyfect.ai.amazon_bedrock.config import AmazonBedrockConfig

__all__ = [
    "AmazonBedrockClient",
    "AmazonBedrockConfig",
    "client",
    "config",
    "language_model",
    "schema",
]
