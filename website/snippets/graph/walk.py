from pyfect import graph


def tasks(m: graph.MutableDirectedGraph[str, None]) -> None:
    fetch, parse, index, report = (m.add_node(t) for t in ("fetch", "parse", "index", "report"))
    m.add_edge(fetch, parse, None)
    m.add_edge(parse, index, None)
    m.add_edge(parse, report, None)
    m.add_edge(index, report, None)


pipeline = graph.directed(tasks)

# Walkers are lazy and repeatable; each iteration starts over.
print(list(pipeline.topo().values()))
print(list(pipeline.bfs(start=[0]).indices()))
print(list(pipeline.dfs(start=[3], direction="incoming").values()))
print(pipeline.is_acyclic(), pipeline.find_cycle())
print(pipeline.to_mermaid(edge_label=lambda _: ""))
