"""The image value of a ``decision.Image`` field (Effect's
``DecisionModel.Image``), shared by ``decision`` and ``decision_model``."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect._url import Url


@dataclass(frozen=True)
class Image:
    """An image in the input: base64 text, bytes or a URL, with its media
    type. Declare it with a ``decision.Image`` field."""

    media_type: str
    data: str | bytes | Url


__all__ = ["Image"]
