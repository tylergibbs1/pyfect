"""Reading configuration text: JSON with comments, JSON5, TOML and YAML."""

from pyfect.encoding import json5, jsonc, toml, yaml

print(jsonc.parse('{ "port": 8080 } // the default'))
print(json5.parse("{ port: 0x1F90, hosts: ['a', 'b',], }"))
print(toml.parse("port = 8080\n[database]\nhost = 'localhost'"))
print(toml.parse("port = "))
print(yaml.parse("base: &base {retries: 3}\nprod:\n  <<: *base\n  port: 443\n"))
