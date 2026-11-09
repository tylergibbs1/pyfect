"""Unicode Normalization Form C (UAX #15) over the generated Unicode 17
tables, so a host normalizes as in Node whatever ``unicodedata`` version the
running Python has."""

from __future__ import annotations

from pyfect._whatwg_url import _unicode as uni

_S_BASE, _L_BASE, _V_BASE, _T_BASE = 0xAC00, 0x1100, 0x1161, 0x11A7
_L_COUNT, _V_COUNT, _T_COUNT = 19, 21, 28
_N_COUNT = _V_COUNT * _T_COUNT
_S_COUNT = _L_COUNT * _N_COUNT


def normalize(text: str) -> str:
    if text.isascii():
        return text
    return _compose(_reorder(_decompose(text)))


def _decompose(text: str) -> list[str]:
    out: list[str] = []
    for ch in text:
        _decompose_into(ch, out)
    return out


def _decompose_into(ch: str, out: list[str]) -> None:
    index = ord(ch) - _S_BASE
    if 0 <= index < _S_COUNT:
        out.append(chr(_L_BASE + index // _N_COUNT))
        out.append(chr(_V_BASE + index % _N_COUNT // _T_COUNT))
        if index % _T_COUNT:
            out.append(chr(_T_BASE + index % _T_COUNT))
        return
    parts = uni.decomposition(ch)
    if parts is None:
        out.append(ch)
        return
    for part in parts:
        _decompose_into(part, out)


def _reorder(chars: list[str]) -> list[str]:
    """The canonical ordering algorithm: a stable sort of each run of
    non-starters by combining class."""
    out: list[str] = []
    run: list[str] = []
    for ch in chars:
        if uni.combining_class(ch) == 0:
            out.extend(sorted(run, key=uni.combining_class))
            run.clear()
            out.append(ch)
        else:
            run.append(ch)
    out.extend(sorted(run, key=uni.combining_class))
    return out


def _compose_pair(first: str, second: str) -> str | None:
    l_index, v_index = ord(first) - _L_BASE, ord(second) - _V_BASE
    if 0 <= l_index < _L_COUNT and 0 <= v_index < _V_COUNT:
        return chr(_S_BASE + (l_index * _V_COUNT + v_index) * _T_COUNT)
    s_index, t_index = ord(first) - _S_BASE, ord(second) - _T_BASE
    if 0 <= s_index < _S_COUNT and s_index % _T_COUNT == 0 and 0 < t_index < _T_COUNT:
        return chr(ord(first) + t_index)
    return uni.compositions().get(first + second)


def _compose(chars: list[str]) -> str:
    out: list[str] = []
    starter: int | None = None  # index in ``out`` of the last starter
    last_class = -1
    for ch in chars:
        cls = uni.combining_class(ch)
        if starter is not None and (last_class < cls or (last_class == 0 and cls == 0)):
            composed = _compose_pair(out[starter], ch)
            if composed is not None:
                out[starter] = composed
                continue
        if cls == 0:
            starter = len(out)
        last_class = cls
        out.append(ch)
    return "".join(out)
