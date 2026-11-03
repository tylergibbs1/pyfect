"""``Unsubscripted``: the default type argument of a class whose constructors
honour a subscript.

``Ref[int | None].make(None)`` makes a ``Ref[int | None]``, and ``Ref.make(None)``
infers a ``Ref[None]``. Pyright gives a class written without type arguments
``Unknown`` ones, which no overload can tell from a subscript, so the class's
type parameters default to this marker: an overload for ``type[Ref[Unsubscripted]]``
infers from the arguments, the next takes the subscript
(research/typing/ctor_1_subscript.py). A bare annotation (``r: Ref``) gets the marker
too, so using it is a type error naming ``Unsubscripted``.
"""

from typing import Never, final


@final
class Unsubscripted:
    """Never instantiated: it only stands for a missing type argument."""

    __slots__ = ()

    def __new__(cls) -> Never:
        raise TypeError("Unsubscripted only stands for a missing type argument")
