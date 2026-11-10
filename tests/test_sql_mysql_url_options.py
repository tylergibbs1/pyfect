"""mysql2's options in a ``mysql://`` URL's query (Effect hands the URL to mysql2): values
are JSON, or else text; the URL's own keys are skipped; ``ssl`` is an object (a profile
name or ``true`` is refused, as mysql2 refuses them); options pyfect does not read are
refused when the config is made instead of being dropped."""

import ssl

import pytest

from pyfect import redacted
from pyfect.duration import millis
from pyfect.sql import mysql
from pyfect.sql.mysql.config import parse_url


def test_reads_ssl_as_a_json_object():
    tls = parse_url('mysql://h/db?ssl={"rejectUnauthorized":false,"minVersion":"TLSv1.2"}')
    assert tls.options.tls is not None
    assert tls.options.tls.reject_unauthorized is False
    context = tls.options.tls.context()
    assert context.verify_mode == ssl.CERT_NONE
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_checks_the_certificate_but_not_the_host_name_by_default():
    parts = parse_url("mysql://h/db?ssl=%7B%7D")
    assert parts.options.tls is not None
    context = parts.options.tls.context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is False
    verified = parse_url('mysql://h/db?ssl={"verifyIdentity":true}').options.tls
    assert verified is not None
    assert verified.context().check_hostname is True


def test_false_or_absent_ssl_turns_tls_off():
    assert parse_url("mysql://h/db").options.tls is None
    assert parse_url("mysql://h/db?ssl=false").options.tls is None


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("ssl=true", "SSL profile must be an object, instead it's a boolean"),
        ("ssl=1", "SSL profile must be an object, instead it's a number"),
        ("ssl=Amazon+RDS", '"Amazon RDS" SSL profile is not bundled'),
        ("ssl=custom", "Unknown SSL profile 'custom'"),
        ('ssl={"pfx":"x"}', "not supported: pfx"),
        ('ssl={"key":"x"}', "needs ssl.cert"),
        ('ssl={"minVersion":"SSLv3"}', "not a TLS version"),
        ("charset=utf8mb4", "not supported: charset"),
        ("connectTimeout=soon", "must be milliseconds"),
    ],
)
def test_refuses_options_it_does_not_read(query: str, message: str):
    with pytest.raises(ValueError, match=message):
        mysql.MysqlClientConfig(url=redacted.make(f"mysql://h/db?{query}"))


def test_reads_connect_timeout_in_milliseconds_and_skips_the_urls_own_keys():
    parts = parse_url("mysql://u@h/db?connectTimeout=2500&user=other&host=elsewhere")
    assert parts.options.connect_timeout == millis(2500)
    assert (parts.host, parts.username) == ("h", "u")
    config = mysql.MysqlClientConfig(url=redacted.make("mysql://h/db?connectTimeout=2500"))
    assert mysql.client.connect_options(config)["connect_timeout"] == 2.5
