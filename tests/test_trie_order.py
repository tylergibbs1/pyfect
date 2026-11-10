"""``Trie`` orders keys by UTF-16 code units, as JavaScript compares
strings, not by Python's code points."""

from pyfect.option import Some
from pyfect.trie import Trie


def test_astral_characters_sort_below_the_private_use_area() -> None:
    trie = Trie.make(("", 1), ("\U0001f600", 2), ("a", 3))
    assert list(trie.keys()) == ["a", "\U0001f600", ""]
    assert sorted(["", "\U0001f600"]) == ["", "\U0001f600"]  # Python's own order


def test_the_empty_key_is_stored_first() -> None:
    """Effect 4.1.2 stores ``""`` like any other key (it was dropped before)."""
    trie = Trie.make(("b", 2), ("", 1))
    assert list(trie) == [("", 1), ("b", 2)]
    assert trie.get("") == Some(1)
    assert trie.modify("", lambda v: v + 1).get("") == Some(2)
    assert Trie.empty().remove("") == Trie.empty()
