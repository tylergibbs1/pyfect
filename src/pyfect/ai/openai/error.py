"""The metadata an OpenAI error carries under ``"openai"`` (Effect's
``OpenAiError``): the error code, type and request id, with the
``x-ratelimit-*`` headers for a rate limit."""

from pyfect.ai._openai_errors import ErrorMetadata as OpenAiErrorMetadata
from pyfect.ai._openai_errors import RateLimitMetadata as OpenAiRateLimitMetadata

__all__ = ["OpenAiErrorMetadata", "OpenAiRateLimitMetadata"]
