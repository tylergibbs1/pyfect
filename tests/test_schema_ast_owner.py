"""``owner`` is the node whose body a node shares; ``key_context_owner`` the node it is with only
its key context changed. A flip's encoded side shares a body but has its own encoding, so a
derivation must derive it itself."""

from pyfect import schema as S
from pyfect.schema import ast


def test_a_key_context_copy_is_one_schema_with_its_original() -> None:
    node = S.FiniteFromString.ast
    copied = ast.replace_context(node, key_annotations=None, optional_key=True)
    assert copied is not node
    assert copied.owner() is node.owner()
    assert copied.key_context_owner() is node


def test_a_flip_shares_a_body_but_not_a_key_context_owner() -> None:
    flipped = S.FiniteFromString.ast.flip()
    assert flipped.encoding is not None
    assert flipped.owner() is not flipped
    assert flipped.owner().encoding is not flipped.encoding
    assert flipped.key_context_owner() is flipped


def test_a_node_without_copies_is_its_own_owner() -> None:
    node = S.String.ast
    assert node.owner() is node
    assert node.key_context_owner() is node


def test_a_flipped_codec_is_derived_with_its_own_encoding() -> None:
    # Derived as its owner's codec, the flip would decode strings instead of encoding them.
    flipped = S.flip(S.FiniteFromString)
    codec = S.to_codec_json(flipped)
    assert S.decode_unknown_sync(codec)(1.5) == "1.5"
    assert S.encode_sync(codec)("1.5") == 1.5
