"""SQL Server names: ``[quoted]``, ``]`` doubled, each dot a boundary
between quoted parts (``a.b`` is ``[a].[b]``)."""


def escape(name: str) -> str:
    return "[" + name.replace("]", "]]").replace(".", "].[") + "]"


__all__ = ["escape"]
