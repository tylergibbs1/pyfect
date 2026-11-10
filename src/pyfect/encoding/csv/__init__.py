"""CSV channels, with optional schemas (Effect's ``encoding/Csv``).

RFC 4180 with a configurable delimiter. Cells are strings, kept as they are
(whitespace and empty cells included); quoted fields may hold delimiters,
line breaks and doubled quotes. Decoders accept LF, CRLF and CR and skip a
leading byte-order mark. Use the channels with ``Stream.pipe_through_channel``::

    from pyfect.encoding import csv

    records = text_stream.pipe_through_channel(csv.decode_string(headers=True))

``decode_schema_string`` / ``encode_schema_string`` (and their byte forms)
decode records to typed values, or encode values to records, with a schema.
"""

from pyfect._public import publish
from pyfect.encoding.csv._channels import (
    DEFAULT_MAX_RECORD_SIZE,
    HeaderRecord,
    Newline,
    decode,
    decode_string,
    encode,
    encode_string,
)
from pyfect.encoding.csv._error import CsvError, CsvErrorKind, Row, is_csv_error
from pyfect.encoding.csv._schema import (
    decode_schema,
    decode_schema_string,
    encode_schema,
    encode_schema_string,
)

__all__ = [
    "DEFAULT_MAX_RECORD_SIZE",
    "CsvError",
    "CsvErrorKind",
    "HeaderRecord",
    "Newline",
    "Row",
    "decode",
    "decode_schema",
    "decode_schema_string",
    "decode_string",
    "encode",
    "encode_schema",
    "encode_schema_string",
    "encode_string",
    "is_csv_error",
]

publish(globals())
