"""``S.Graph`` as a declaration (not through its JSON codec): it takes an
immutable graph of its kind and parses the payloads in place."""

import pytest

from pyfect import graph
from pyfect import schema as S


def test_declaration_checks_the_graph_and_its_payloads():
    """The declaration takes an immutable graph of its kind and parses its payloads."""
    schema = S.Graph("directed", S.String, S.Number)

    def build(m: graph.MutableGraph[object, object]) -> None:
        m.add_edge(m.add_node("A"), m.add_node(1), 2)

    assert S.is_(schema)(graph.directed(lambda m: m.add_node("A")))
    assert not S.is_(schema)(graph.undirected())
    assert not S.is_(schema)(graph.directed().begin_mutation())
    with pytest.raises(Exception, match=r'Expected string\n  at \["nodes"\]\[1\]\["data"\]'):
        S.decode_unknown_sync(schema)(graph.directed(build))
