"""HTTP middleware (Effect's ``HttpMiddleware``): functions from an app to
an app.

- ``logger``: logs each response (``with_logger_disabled`` opts out)
- ``tracer``: a server span per request (``TracerDisabledWhen``,
  ``SpanNameGenerator``, ``TracerHeaderFilter``)
- ``x_forwarded_headers``: the client address behind trusted proxies
- ``search_params_parser``: provides ``ParsedSearchParams``
- ``cors``, ``compression``, ``decompression``
"""

from pyfect.http._vary import vary_with
from pyfect.http.middleware._compression import (
    compression,
    default_compressible,
    negotiate,
    parse_accept_encoding,
)
from pyfect.http.middleware._cors import cors
from pyfect.http.middleware._decompression import (
    DecompressedRequest,
    decompression,
    parse_content_encoding,
)
from pyfect.http.middleware._forwarded import TrustedProxies, x_forwarded_headers
from pyfect.http.middleware._logger import logger, strip_search_and_hash, with_logger_disabled
from pyfect.http.middleware._search_params import search_params_parser
from pyfect.http.middleware._tracer import (
    SpanNameGenerator,
    TracerDisabledWhen,
    TracerHeaderFilter,
    is_tracer_disabled_unsafe,
    layer_tracer_disabled_for_urls,
    tracer,
)
from pyfect.http.middleware._types import AppMiddleware

__all__ = [
    "AppMiddleware",
    "DecompressedRequest",
    "SpanNameGenerator",
    "TracerDisabledWhen",
    "TracerHeaderFilter",
    "TrustedProxies",
    "compression",
    "cors",
    "decompression",
    "default_compressible",
    "is_tracer_disabled_unsafe",
    "layer_tracer_disabled_for_urls",
    "logger",
    "negotiate",
    "parse_accept_encoding",
    "parse_content_encoding",
    "search_params_parser",
    "strip_search_and_hash",
    "tracer",
    "vary_with",
    "with_logger_disabled",
    "x_forwarded_headers",
]
