"""The query parser of find-my-way (``fast-querystring``'s ``parse``)."""

from __future__ import annotations

from pyfect._js import decode_uri_component


def _decode(text: str) -> str:
    try:
        return decode_uri_component(text) or text
    except ValueError:
        return text


def parse(text: str) -> dict[str, str | list[str]]:  # noqa: PLR0912
    """Each key's value, or values when repeated. ``+`` is a space; a key
    or value is percent-decoded only when it holds a ``%`` (a value also
    when it holds a second ``=``), and left as it is when malformed."""
    result: dict[str, str | list[str]] = {}
    length = len(text)
    start = -1
    equals = -1
    decode_key = decode_value = key_plus = value_plus = False
    for index in range(length + 1):
        char = text[index] if index != length else "&"
        if char == "&":
            has_pair = equals > start
            if not has_pair:
                equals = index
            key = text[start + 1 : equals]
            if has_pair or key:
                if key_plus:
                    key = key.replace("+", " ")
                if decode_key:
                    key = _decode(key)
                value = ""
                if has_pair:
                    value = text[equals + 1 : index]
                    if value_plus:
                        value = value.replace("+", " ")
                    if decode_value:
                        value = _decode(value)
                current = result.get(key)
                if current is None:
                    result[key] = value
                elif isinstance(current, list):
                    current.append(value)
                else:
                    result[key] = [current, value]
            start = equals = index
            decode_key = decode_value = key_plus = value_plus = False
        elif char == "=":
            if equals <= start:
                equals = index
            else:
                decode_value = True
        elif char == "+":
            if equals > start:
                value_plus = True
            else:
                key_plus = True
        elif char == "%":
            if equals > start:
                decode_value = True
            else:
                decode_key = True
    return result
