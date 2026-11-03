from pyfect import graph


def roads(m: graph.MutableUndirectedGraph[str, float]) -> None:
    oslo, bergen, trondheim = m.add_node("Oslo"), m.add_node("Bergen"), m.add_node("Trondheim")
    m.add_edge(oslo, bergen, 463)
    m.add_edge(oslo, trondheim, 494)
    m.add_edge(bergen, trondheim, 633)


towns = graph.undirected(roads)
print(towns)
print(towns.neighbors(0), towns.degree(0))


def add_tromso(m: graph.MutableUndirectedGraph[str, float]) -> None:
    tromso = m.add_node("Tromsø")  # indexes are never reused: this is 3
    m.add_edge(tromso, 2, 1140)


# A graph never changes: mutate edits a private copy and returns a new graph.
grown = towns.mutate(add_tromso)
print(towns.node_count(), grown.node_count())
print(grown.dijkstra(source=1, target=3, cost=float))
print(towns == graph.undirected(roads))
