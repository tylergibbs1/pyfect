"""The metadata an OpenAI-compatible error carries under
``"openai-compat"`` (Effect's ``OpenAiError``)."""

from pyfect.ai._openai_errors import ErrorMetadata as OpenAiErrorMetadata
from pyfect.ai._openai_errors import RateLimitMetadata as OpenAiRateLimitMetadata

__all__ = ["OpenAiErrorMetadata", "OpenAiRateLimitMetadata"]
