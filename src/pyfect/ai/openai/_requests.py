"""What every request of both OpenAI clients (``client``,
``client_generated``) carries."""

from __future__ import annotations

from collections.abc import Callable

from pyfect._js import or_default
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_API_URL = "https://api.openai.com/v1"


def prepare_requests(
    api_key: Redacted[str] | None,
    api_url: str | None,
    organization_id: Redacted[str] | None,
    project_id: Redacted[str] | None,
) -> Callable[[HttpClientRequest], HttpClientRequest]:
    """The URL, credentials and headers every OpenAI request carries."""

    def prepare(request: HttpClientRequest) -> HttpClientRequest:
        request = request.prepend_url(or_default(api_url, DEFAULT_API_URL))
        if api_key is not None:
            request = request.bearer_token(redacted_value(api_key))
        if organization_id is not None:
            request = request.set_header("openai-organization", redacted_value(organization_id))
        if project_id is not None:
            request = request.set_header("openai-project", redacted_value(project_id))
        return request.accept_json()

    return prepare
