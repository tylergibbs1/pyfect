from datetime import UTC, datetime

from pyfect.encoding import ini, toml, yaml
from pyfect.result import Err, Ok

# TOML: a Result. A date-time with an offset becomes a UTC datetime.
match toml.parse(
    """
title = "shop"

[server]
port = 8080
started = 1979-05-27T07:32:00-08:00

[[products]]
name = "hammer"

[[products]]
name = "nail"
"""
):
    case Ok(config):
        print(config["server"]["port"], [p["name"] for p in config["products"]])
        assert config["server"]["started"] == datetime(1979, 5, 27, 15, 32, tzinfo=UTC)
    case Err(error):
        raise AssertionError(error)

match toml.parse("a = 1\na = 2"):
    case Err(error):
        print(error.message)
    case Ok():
        raise AssertionError("a key defined twice")

# YAML: the value, or ValueError. Merge keys copy a mapping; explicit keys win.
settings = yaml.parse(
    """
base: &base
  retries: 3
  timeout: 5
prod:
  <<: *base
  timeout: 30
"""
)
print(settings)
assert settings == {"base": {"retries": 3, "timeout": 5}, "prod": {"retries": 3, "timeout": 30}}

try:
    yaml.parse("hosts: [a, b")
except ValueError as error:
    print("invalid YAML:", error)

# INI: never fails. Quotes are removed before true / false / null are read.
parsed = ini.parse('debug = true\nname = "true"\n[db.main]\nhost = localhost\nflag')
print(parsed)
assert parsed["name"] is True  # the string "true" can't be written
