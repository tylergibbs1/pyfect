"""``Trie`` orders keys by UTF-16 code units, as JavaScript compares
strings, not by Python's code points."""

from pyfect.trie import Trie


def test_astral_characters_sort_below_the_private_use_area() -> None:
    trie = Trie.make(("", 1), ("\U0001f600", 2), ("a", 3))
    assert list(trie.keys()) == ["a", "\U0001f600", ""]
    assert sorted(["", "\U0001f600"]) == ["", "\U0001f600"]  # Python's own order


def test_the_empty_key_is_never_stored() -> None:
    trie = Trie.make(("", 1))
    assert trie.is_empty()
    assert trie.insert("", 2) is trie
    assert trie.get("") is None
