"""WHATWG's "domain to ASCII": UTS #46 ToASCII with CheckHyphens,
UseSTD3ASCIIRules, Transitional_Processing and VerifyDnsLength off and
CheckBidi and CheckJoiners on, over Punycode (RFC 3492)."""

from __future__ import annotations

from pyfect._whatwg_url import _nfc
from pyfect._whatwg_url import _unicode as uni

_BASE, _TMIN, _TMAX, _SKEW, _DAMP = 36, 1, 26, 38, 700
_MAX_INT = 0x7FFFFFFF  # RFC 3492's overflow bound, as Node's decoder checks it


def _adapt(delta: int, points: int, first: bool) -> int:
    delta = delta // _DAMP if first else delta // 2
    delta += delta // points
    k = 0
    while delta > ((_BASE - _TMIN) * _TMAX) // 2:
        delta //= _BASE - _TMIN
        k += _BASE
    return k + (_BASE - _TMIN + 1) * delta // (delta + _SKEW)


def _threshold(k: int, bias: int) -> int:
    return _TMIN if k <= bias else _TMAX if k >= bias + _TMAX else k - bias


def _digit(ch: str) -> int | None:
    if "a" <= ch <= "z":
        return ord(ch) - ord("a")
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A")
    if "0" <= ch <= "9":
        return ord(ch) - ord("0") + 26
    return None


def punycode_decode(text: str) -> str | None:  # noqa: PLR0911
    """RFC 3492 decoding; ``None`` for bad input or overflow."""
    delimiter = text.rfind("-")
    output = list(text[:delimiter]) if delimiter > 0 else []
    if any(ord(ch) >= 0x80 for ch in output):
        return None
    rest = text[delimiter + 1 :] if delimiter > 0 else text
    n, i, bias, pos = 0x80, 0, 72, 0
    while pos < len(rest):
        old_i, w, k = i, 1, _BASE
        while True:
            if pos >= len(rest):
                return None
            digit = _digit(rest[pos])
            pos += 1
            if digit is None or digit > (_MAX_INT - i) // w:
                return None
            i += digit * w
            t = _threshold(k, bias)
            if digit < t:
                break
            if w > _MAX_INT // (_BASE - t):
                return None
            w *= _BASE - t
            k += _BASE
        size = len(output) + 1
        bias = _adapt(i - old_i, size, old_i == 0)
        if i // size > _MAX_INT - n:
            return None
        n += i // size
        i %= size
        if n > 0x10FFFF:
            return None
        output.insert(i, chr(n))
        i += 1
    return "".join(output)


def punycode_encode(text: str) -> str:
    """RFC 3492 encoding (without the ``xn--`` prefix)."""
    points = [ord(ch) for ch in text]
    output = [ch for ch in text if ord(ch) < 0x80]
    basic = handled = len(output)
    if basic:
        output.append("-")
    n, delta, bias = 0x80, 0, 72
    while handled < len(points):
        m = min(p for p in points if p >= n)
        delta += (m - n) * (handled + 1)
        n = m
        for p in points:
            if p < n:
                delta += 1
            elif p == n:
                q, k = delta, _BASE
                while True:
                    t = _threshold(k, bias)
                    if q < t:
                        break
                    digit = t + (q - t) % (_BASE - t)
                    output.append("abcdefghijklmnopqrstuvwxyz0123456789"[digit])
                    q = (q - t) // (_BASE - t)
                    k += _BASE
                output.append("abcdefghijklmnopqrstuvwxyz0123456789"[q])
                bias = _adapt(delta, handled + 1, handled == basic)
                delta = 0
                handled += 1
        delta += 1
        n += 1
    return "".join(output)


def _map(domain: str) -> str | None:
    out: list[str] = []
    for ch in domain:
        status = uni.idna_status(ch)
        if status == "V":
            out.append(ch)
        elif status.startswith("M"):
            out.extend(chr(int(cp, 16)) for cp in status[2:].split())
        elif status == "X":
            return None
    return "".join(out)


def _joiners_ok(label: str) -> bool:
    """RFC 5892's CONTEXTJ rules for U+200C and U+200D."""
    for i, ch in enumerate(label):
        if ch not in "‌‍":
            continue
        if i > 0 and uni.is_virama(label[i - 1]):
            continue
        if ch == "‍":
            return False
        before = (uni.joining_type(c) for c in reversed(label[:i]))
        after = (uni.joining_type(c) for c in label[i + 1 :])
        if next((t for t in before if t != "T"), None) not in ("L", "D"):
            return False
        if next((t for t in after if t != "T"), None) not in ("R", "D"):
            return False
    return True


_RTL = frozenset({"R", "AL"})
_RTL_ALLOWED = frozenset({"R", "AL", "AN", "EN", "ES", "CS", "ET", "ON", "BN", "NSM"})
_LTR_ALLOWED = frozenset({"L", "EN", "ES", "CS", "ET", "ON", "BN", "NSM"})


def _bidi_ok(label: str) -> bool:
    """The six conditions of RFC 5893 section 2."""
    classes = [uni.bidi_class(ch) for ch in label]
    last = next((c for c in reversed(classes) if c != "NSM"), None)
    if classes[0] in _RTL:
        return (
            all(c in _RTL_ALLOWED for c in classes)
            and last in ("R", "AL", "EN", "AN")
            and not ("EN" in classes and "AN" in classes)
        )
    if classes[0] == "L":
        return all(c in _LTR_ALLOWED for c in classes) and last in ("L", "EN")
    return False


def _valid(label: str) -> bool:
    return (
        _nfc.normalize(label) == label
        and not label.startswith("xn--")
        and "." not in label
        and not uni.is_mark(label[0])
        and all(uni.idna_status(ch) == "V" for ch in label)
        and _joiners_ok(label)
    )


def _is_bidi_domain(labels: list[str]) -> bool:
    return any(uni.bidi_class(ch) in ("R", "AL", "AN") for label in labels for ch in label)


def to_ascii(domain: str) -> str | None:
    """``domain`` in ASCII, ``None`` when UTS #46 records an error."""
    mapped = _map(domain)
    if mapped is None:
        return None
    labels = _nfc.normalize(mapped).split(".")
    for index, label in enumerate(labels):
        if label.startswith("xn--"):
            decoded = punycode_decode(label[4:]) if label.isascii() else None
            if not decoded or decoded.isascii():
                return None
            labels[index] = decoded
    if not all(_valid(label) for label in labels if label):
        return None
    if _is_bidi_domain(labels) and not all(_bidi_ok(label) for label in labels if label):
        return None
    return ".".join(
        label if label.isascii() else "xn--" + punycode_encode(label) for label in labels
    )
