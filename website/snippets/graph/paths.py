from pyfect import graph


def network(m: graph.MutableDirectedGraph[str, int]) -> None:
    a, b, c, d = (m.add_node(name) for name in "ABCD")
    m.add_edge(a, b, 4)
    m.add_edge(a, c, 1)
    m.add_edge(c, b, 2)
    m.add_edge(b, d, 1)
    m.add_edge(c, d, 5)


g = graph.directed(network)

shortest = g.dijkstra(source=0, target=3, cost=float)
assert shortest is not None
print(shortest.path, shortest.distance)

# None when the target can't be reached.
print(g.dijkstra(source=3, target=0, cost=float))

every = g.floyd_warshall(float)
print(every.distances[0])

for found in g.simple_paths(source=0, target=3):
    print(found.path, found.costs)

flow = g.maximum_flow(source=0, target=3, capacity=float)
print(flow.value, flow.cut)
