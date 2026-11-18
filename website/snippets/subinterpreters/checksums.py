"""Pure functions a subinterpreter imports and runs: this module imports nothing
heavy, so starting it there is quick."""


def checksum(data: bytes) -> int:
    # Stands in for CPU-heavy pure-Python work: parsing, scoring, a model.
    total = 0
    for byte in data:
        total = (total * 31 + byte) % 1_000_000_007
    return total


def parse_port(text: str) -> int:
    port = int(text)
    if not 0 < port < 65536:
        raise ValueError(f"port out of range: {port}")
    return port
