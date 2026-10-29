"""Media types compared without case, parameters or surrounding space."""


def normalize(content_type: str) -> str:
    """``"Application/JSON; charset=utf-8"`` is ``"application/json"``."""
    return content_type.lower().strip().split(";", 1)[0].strip()
