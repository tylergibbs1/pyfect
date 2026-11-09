"""``pyfect._js.js_string`` is JavaScript's ``String(value)`` for the values
Python code hands it, so every port of ``String(...)`` (graph labels, schema
coercion, INI values, CLI messages) writes what Effect writes. Expected texts
printed by Node 24 (``String([1, 2])`` and so on).

A list or tuple is an array: its items joined by ``,``, ``null`` and
``undefined`` items empty (dogfood apps #8: a graph's default label was
Python's ``[1, 2]``); a dict is a plain object, ``[object Object]``.
"""

import pytest

from pyfect._js import js_string

_CASES: list[tuple[object, str]] = [
    ([1, 2], "1,2"),
    ((1, 2), "1,2"),
    ([1, [2, 3]], "1,2,3"),
    ([None, None, 1], ",,1"),
    ([], ""),
    ([[]], ""),
    ({"a": 1}, "[object Object]"),
    ([{"a": 1}], "[object Object]"),
    ([True, 1.5, "x"], "true,1.5,x"),
    ([2.0, -0.0], "2,0"),
    (None, "null"),
    (True, "true"),
    (1.0, "1"),
    ("x", "x"),
]


@pytest.mark.parametrize(("value", "expected"), _CASES)
def test_js_string_writes_what_javascript_string_writes(value: object, expected: str):
    assert js_string(value) == expected


def test_a_graphs_default_label_is_javascripts_string_of_the_data():
    from pyfect import graph

    def build(m: graph.MutableUndirectedGraph[list[int], None]) -> None:
        m.add_node([1, 2])

    g = graph.undirected(build)
    # Effect: Graph.toGraphViz / toMermaid of a node [1, 2]
    assert g.to_graph_viz() == 'graph "G" {\n  "0" [label="1,2"];\n}'
    assert '0["1,2"]' in g.to_mermaid()
