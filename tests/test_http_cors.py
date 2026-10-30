"""pyfect-specific CORS behaviour: configurations browsers reject fail
when the middleware is built."""

import pytest

from pyfect.http.middleware import cors


def test_credentials_with_every_origin_allowed_is_refused_when_built():
    # "Access-Control-Allow-Origin: *" with credentials is refused by browsers.
    with pytest.raises(ValueError, match="allowed_origins"):
        cors(credentials=True)


def test_credentials_with_listed_or_tested_origins_are_allowed():
    cors(credentials=True, allowed_origins=["https://a.example"])
    cors(credentials=True, allowed_origins=lambda origin: origin.endswith(".example"))


@pytest.mark.parametrize("origins", [["*"], ["https://a.example", "*"]])
def test_credentials_with_a_listed_wildcard_are_refused_when_built(origins: list[str]):
    with pytest.raises(ValueError, match="allowed_origins"):
        cors(credentials=True, allowed_origins=origins)
