"""Decoding CSV records with a schema, and writing them back."""

from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.encoding import csv


class Person(TypedDict):
    name: str
    age: float


# Columns that are not strings go through the StringTree codec; headers can be renamed.
people = S.Struct(Person).pipe(S.encode_keys({"name": "Full Name", "age": "Age (years)"}))

text = 'Full Name,Age (years)\n"Smith, Charlie",32\nAda,36\n'
decoded = stream.make(text).pipe_through_channel(csv.decode_schema_string(people, headers=True))
records = fx.run_blocking(decoded.run_collect().or_die())
print(records)

written = stream.from_iterable(records).pipe_through_channel(
    csv.encode_schema_string(people, headers=True, newline="\n")
)
print(fx.run_blocking(written.run_string().or_die()), end="")

# A bad cell fails with a SchemaError whose path starts with the record number.
bad = stream.make("Full Name,Age (years)\nAda,old\n").pipe_through_channel(
    csv.decode_schema_string(people, headers=True)
)
print(fx.run_blocking(bad.run_collect().flip().or_die()))
