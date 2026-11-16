"""``LegacyStoreNeedsMigration.automatic`` (0.6.8) stays readable in 0.6.9 as a deprecated
property, so code written against 0.6.8 keeps working in a patch release."""

import pytest

from pyfect.eventlog.sql_event_log_server_encrypted import LegacyStoreNeedsMigration


@pytest.mark.parametrize(
    ("state", "automatic"),
    [("pending", True), ("ambiguous", True), ("unbound", True), ("unconfirmed", False)],
)
def test_automatic_is_a_deprecated_reading_of_state(state: str, automatic: bool) -> None:
    error = LegacyStoreNeedsMigration(public_key="k", store_id="a/b", state=state)  # pyright: ignore[reportArgumentType]
    with pytest.deprecated_call(match="read .state instead"):
        assert error.automatic is automatic  # pyright: ignore[reportDeprecated]
