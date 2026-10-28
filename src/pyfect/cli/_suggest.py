"""Did-you-mean suggestions for mistyped flags and subcommands (Effect's
internal ``cli/internal/auto-suggest``)."""

from __future__ import annotations

from collections.abc import Sequence


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            cost = 0 if char_a == char_b else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def suggest(text: str, candidates: Sequence[str]) -> tuple[str, ...]:
    """The candidates closest to ``text``, within an edit distance of 2."""
    scored = sorted(
        (
            (distance, candidate)
            for candidate in candidates
            if (distance := _levenshtein(text, candidate)) <= 2
        ),
        key=lambda pair: pair[0],
    )
    if not scored:
        return ()
    best = scored[0][0]
    return tuple(candidate for distance, candidate in scored if distance == best)
