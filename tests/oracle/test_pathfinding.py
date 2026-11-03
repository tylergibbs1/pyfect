"""Ports of Effect's ``test/Pathfinding.test.ts``: Dijkstra, Bellman-Ford
and A* on an ASCII terrain grid.

Each test's docstring is the Effect test title. A path is compared as its
start and a string of moves; a mismatch prints both paths over the grid
(without Effect's ANSI colors).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from pyfect import graph
from pyfect.graph import PathResult

SIMPLE = """
    ##############################
    #.........#......#...........#
    #...####.#..~~~~##..^^^^^....#
    #...####....~~~~....^^^^^....#
    #...........~~~~....^^^^^....#
    #...........~~~~##...........#
    #...MMMM.........#...........#
    #...MMMM.........#...........#
    #...MMMM.........#...........#
    #................#...........#
    #................#...........#
    #...^^^^^....####....~~~~....#
    #...^^^^^....####....~~~~....#
    #................#...........#
    ##############################
"""

WEIGHTS = {"#": None, ".": 1, "~": 3, "^": 5, "M": 2}
"""Cost of entering a cell; ``None`` is a wall. Other characters cost 1."""


@dataclass(frozen=True)
class TerrainNode:
    x: int
    y: int
    type: str
    weight: int


@dataclass(frozen=True)
class Terrain:
    graph: graph.DirectedGraph[TerrainNode, int]
    grid: list[str]
    nodes: dict[tuple[int, int], int]
    coordinates: dict[int, tuple[int, int]]


def parse_terrain(ascii_art: str) -> Terrain:
    lines = [line.strip() for line in ascii_art.strip().split("\n") if line.strip()]
    width = len(lines[0])
    assert all(len(line) == width for line in lines)
    nodes: dict[tuple[int, int], int] = {}
    coordinates: dict[int, tuple[int, int]] = {}
    entry_cost: dict[int, int] = {}

    def build(m: graph.MutableDirectedGraph[TerrainNode, int]) -> None:
        for y, line in enumerate(lines):
            for x, char in enumerate(line):
                weight = WEIGHTS.get(char, 1)
                if weight is not None:
                    index = m.add_node(TerrainNode(x, y, char, weight))
                    nodes[x, y] = index
                    coordinates[index] = (x, y)
                    entry_cost[index] = weight
        for (x, y), node in nodes.items():
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                adjacent = nodes.get((x + dx, y + dy))
                if adjacent is not None:
                    m.add_edge(node, adjacent, entry_cost[adjacent])

    return Terrain(graph.directed(build), lines, nodes, coordinates)


_MOVES = {(0, -1): "↑", (0, 1): "↓", (-1, 0): "←", (1, 0): "→"}


def sequence_from_path(terrain: Terrain, result: PathResult[int] | None) -> str | None:
    if result is None or not result.path:
        return None
    points = [terrain.coordinates[index] for index in result.path]
    moves = "".join(_MOVES[bx - ax, by - ay] for (ax, ay), (bx, by) in itertools.pairwise(points))
    x, y = points[0]
    return f"{x}:{y};{moves}"


def path_from_sequence(terrain: Terrain, sequence: str) -> list[tuple[int, int]]:
    start, moves = sequence.split(";")
    x, y = (int(part) for part in start.split(":"))
    points = [(x, y)]
    steps = {move: delta for delta, move in _MOVES.items()}
    for move in moves:
        dx, dy = steps[move]
        x, y = x + dx, y + dy
        if (x, y) in terrain.nodes:
            points.append((x, y))
    return points


def print_solution(terrain: Terrain, points: list[tuple[int, int]]) -> str:
    grid = [list(line) for line in terrain.grid]
    for step, (x, y) in enumerate(points):
        grid[y][x] = "S" if step == 0 else "E" if step == len(points) - 1 else "*"
    return "\n".join("".join(line) for line in grid)


def assert_path(terrain: Terrain, actual: PathResult[int] | None, sequence: str) -> None:
    derived = sequence_from_path(terrain, actual)
    actual_points = [] if actual is None else [terrain.coordinates[i] for i in actual.path]
    assert derived == sequence, "\n".join(
        [
            "Path finding result did not match the expected sequence",
            f"Expected: {sequence}",
            f"Actual:   {derived}",
            "Expected Path:",
            print_solution(terrain, path_from_sequence(terrain, sequence)),
            "Actual Path:",
            print_solution(terrain, actual_points),
        ]
    )


def _weight(weight: int) -> int:
    return weight


def test_should_find_paths_using_dijkstra_algorithm() -> None:
    """should find paths using Dijkstra algorithm"""
    parsed = parse_terrain(SIMPLE)
    result = parsed.graph.dijkstra(
        source=parsed.nodes[1, 1], target=parsed.nodes[28, 13], cost=_weight
    )
    assert_path(parsed, result, "1:1;↓↓↓→→→→→→→→→→→→→→→→→↓↓↓↓↓↓↓↓↓→→→→→→→→→→")


def test_should_find_paths_using_bellman_ford_algorithm() -> None:
    """should find paths using Bellman-Ford algorithm"""
    parsed = parse_terrain(SIMPLE)
    result = parsed.graph.bellman_ford(
        source=parsed.nodes[1, 1], target=parsed.nodes[28, 13], cost=_weight
    )
    assert_path(parsed, result, "1:1;→→→→→→→↓↓→→→→→→→→→→→↓↓→→→→→→→→→↓↓↓↓↓↓↓↓")


def test_should_find_paths_using_a_star_algorithm() -> None:
    """should find paths using A* algorithm"""
    parsed = parse_terrain(SIMPLE)

    def manhattan(source: TerrainNode, target: TerrainNode) -> float:
        return abs(target.x - source.x) + abs(target.y - source.y)

    result = parsed.graph.astar(
        source=parsed.nodes[1, 1], target=parsed.nodes[28, 13], cost=_weight, heuristic=manhattan
    )
    assert_path(parsed, result, "1:1;↓↓↓↓→→→→→→→↓→→→→→→→↑↑→→→↓↓↓↓↓↓↓↓↓→→→→→→→→→→")
