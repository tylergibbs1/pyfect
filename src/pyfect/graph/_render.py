"""GraphViz DOT and Mermaid text, nodes then edges in index order."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from pyfect._js import js_string
from pyfect.graph._records import MermaidDiagramType, MermaidDirection, MermaidNodeShape
from pyfect.graph._store import Store

_NEWLINE = re.compile(r"\r\n|\r|\n")


def _dot_escape(value: str) -> str:
    return _NEWLINE.sub(r"\\n", value.replace("\\", "\\\\").replace('"', '\\"'))


def to_graph_viz(
    store: Store,
    node_label: Callable[[Any], str] | None,
    edge_label: Callable[[Any], str] | None,
    graph_name: str,
) -> str:
    node_text = node_label or js_string
    edge_text = edge_label or js_string
    directed = store.kind == "directed"
    operator = "->" if directed else "--"

    def render() -> str:
        lines = [f'{"digraph" if directed else "graph"} "{_dot_escape(graph_name)}" {{']
        lines += [
            f'  "{node}" [label="{_dot_escape(node_text(data))}"];'
            for node, data in store.nodes.items()
        ]
        lines += [
            f'  "{e.source}" {operator} "{e.target}" [label="{_dot_escape(edge_text(e.data))}"];'
            for e in store.edges.values()
        ]
        lines.append("}")
        return "\n".join(lines)

    return store.guarded(render)


_MERMAID_ESCAPES = (
    ("#", "#35;"),
    ('"', "#quot;"),
    ("<", "#lt;"),
    (">", "#gt;"),
    ("&", "#amp;"),
    ("[", "#91;"),
    ("]", "#93;"),
    ("{", "#123;"),
    ("}", "#125;"),
    ("(", "#40;"),
    (")", "#41;"),
    ("|", "#124;"),
    ("\\", "#92;"),
)

_SHAPES: dict[str, tuple[str, str]] = {
    "rectangle": ('["', '"]'),
    "rounded": ('("', '")'),
    "circle": ('(("', '"))'),
    "diamond": ('{"', '"}'),
    "hexagon": ('{{"', '"}}'),
    "stadium": ('(["', '"])'),
    "subroutine": ('[["', '"]]'),
    "cylindrical": ('[("', '")]'),
}


def _mermaid_escape(label: str) -> str:
    # ``#`` first, so the escapes themselves are not escaped again.
    for raw, escaped in _MERMAID_ESCAPES:
        label = label.replace(raw, escaped)
    return _NEWLINE.sub("<br/>", label)


def to_mermaid(
    store: Store,
    *,
    node_label: Callable[[Any], str] | None,
    edge_label: Callable[[Any], str] | None,
    diagram_type: MermaidDiagramType | None,
    direction: MermaidDirection,
    node_shape: Callable[[Any], MermaidNodeShape] | None,
) -> str:
    node_text = node_label or js_string
    edge_text = edge_label or js_string
    kind = diagram_type or ("flowchart" if store.kind == "directed" else "graph")
    operator = "-->" if kind == "flowchart" else "---"

    def render() -> str:
        lines = [f"{kind} {direction}"]
        for node, data in store.nodes.items():
            label = _mermaid_escape(node_text(data))
            shape = "rectangle" if node_shape is None else node_shape(data)
            opening, closing = _SHAPES.get(shape, _SHAPES["rectangle"])
            lines.append(f"  {node}{opening}{label}{closing}")
        for edge in store.edges.values():
            label = _mermaid_escape(edge_text(edge.data))
            link = f'{operator}|"{label}"|' if label else operator
            lines.append(f"  {edge.source} {link} {edge.target}")
        return "\n".join(lines)

    return store.guarded(render)
