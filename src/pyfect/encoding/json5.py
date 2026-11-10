"""JSON5 text to Python values (Effect's ``encoding/Json5``), without
dependencies: [JSON5 1.0.0](https://spec.json5.org/), as the ``json5`` 2.2.3
package reads values, without its reviver.

``parse`` accepts comments, trailing commas, identifier keys, single-quoted
strings, hexadecimal numbers, ``Infinity`` and ``NaN``. A repeated key keeps
its last value; ``__proto__`` is an ordinary key. Numbers without a fraction
or exponent are ``int``::

    json5.parse("{ port: 8080, }")  # Ok({"port": 8080})
"""

from __future__ import annotations

from pyfect._binary_codecs import EncodingError
from pyfect.encoding import _json_parser
from pyfect.result import Err, Ok, Result


def parse(text: str, /) -> Result[object, EncodingError]:
    """The value of a JSON5 document, or an ``EncodingError`` whose message
    gives the line and column (in UTF-16 code units) without quoting the
    text."""
    try:
        return Ok(_json_parser.parse(text, "JSON5"))
    except ValueError as error:
        return Err(EncodingError(kind="Decode", module="Json5", input=text, message=str(error)))


__all__ = ["parse"]
