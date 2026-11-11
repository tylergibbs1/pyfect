"""The port helpers in ``tests/_ports.py``, and the ban on picking a port
with a probe socket that is closed before the port is used."""

import ast
import socket
from pathlib import Path
from typing import cast

import _ports
import pytest

_TESTS = Path(__file__).parent


def test_tcp_and_udp_move_on_when_the_tcp_port_number_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Another process holds TCP on the port the OS hands out for UDP.
    with socket.create_server(("127.0.0.1", 0)) as taken:
        taken_port = taken.getsockname()[1]
        bind = socket.socket.bind
        forced: list[int] = []

        def first_udp_bind_lands_on_the_taken_port(
            self: socket.socket, address: tuple[str, int]
        ) -> None:
            if self.type == socket.SOCK_DGRAM and address[1] == 0 and not forced:
                forced.append(taken_port)
                address = (address[0], taken_port)
            bind(self, address)

        monkeypatch.setattr(socket.socket, "bind", first_udp_bind_lands_on_the_taken_port)
        tcp, udp = _ports.tcp_and_udp()
        with tcp, udp:
            assert forced == [taken_port]
            port = tcp.getsockname()[1]
            assert port != taken_port
            assert udp.getsockname()[1] == port
            assert tcp.type == socket.SOCK_STREAM
            assert udp.type == socket.SOCK_DGRAM


def test_a_refused_tcp_port_refuses_connects_and_stays_taken() -> None:
    port = _ports.refused_tcp_port()
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=5).close()
    with socket.socket() as other, pytest.raises(OSError):
        other.bind(("127.0.0.1", port))


def test_a_refused_udp_port_refuses_datagrams_and_stays_taken() -> None:
    port = _ports.refused_udp_port()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(5)
        client.connect(("127.0.0.1", port))
        client.send(b"anyone?")
        with pytest.raises(ConnectionRefusedError):
            client.recv(16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other, pytest.raises(OSError):
        other.bind(("127.0.0.1", port))


def test_a_reserved_port_is_kept_from_others_but_open_to_a_reusing_server() -> None:
    port = _ports.reserved_port()
    with socket.socket() as plain, pytest.raises(OSError):
        plain.bind(("127.0.0.1", port))
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen()
        socket.create_connection(("127.0.0.1", port), timeout=5).close()


# --- the ban ------------------------------------------------------------------------------


def _port_reads(node: ast.AST) -> set[str]:
    """Names of sockets whose ``getsockname()`` is read under ``node``."""
    return {
        call.func.value.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "getsockname"
        and isinstance(call.func.value, ast.Name)
    }


def _assigned_ports(statements: list[ast.stmt], sock: str) -> set[str]:
    """Names assigned from ``sock.getsockname()`` in ``statements``."""
    names: set[str] = set()
    for statement in statements:
        for node in ast.walk(statement):
            if isinstance(node, ast.Assign) and sock in _port_reads(node.value):
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _loads(statements: list[ast.stmt]) -> set[str]:
    return {
        node.id
        for statement in statements
        for node in ast.walk(statement)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def _blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    """The statement lists nested directly in ``statement``."""
    blocks: list[list[ast.stmt]] = []
    for node in (statement, *ast.iter_child_nodes(statement)):
        if node is not statement and isinstance(node, ast.stmt):
            continue
        for field in ("body", "orelse", "finalbody"):
            nested: object = getattr(node, field, None)
            if isinstance(nested, list) and nested and isinstance(nested[0], ast.stmt):
                blocks.append(cast(list[ast.stmt], nested))
    return blocks


def _with_frees(statement: ast.With, rest: list[ast.stmt]) -> bool:
    """Whether a port read inside ``with ... as sock`` is returned from it or
    used after it."""
    for item in statement.items:
        if not isinstance(item.optional_vars, ast.Name):
            continue
        sock = item.optional_vars.id
        returned = any(
            isinstance(node, ast.Return)
            and node.value is not None
            and sock in _port_reads(node.value)
            for node in ast.walk(statement)
        )
        if returned or _assigned_ports(statement.body, sock) & _loads(rest):
            return True
    return False


def _calls_free(statement: ast.stmt, rest: list[ast.stmt], ports: dict[str, str]) -> list[int]:
    """Lines in ``statement`` that close a socket whose port is used later,
    or bind a socket to another socket's port."""
    found: list[int] = []
    for node in ast.walk(statement):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            continue
        sock = node.func.value.id
        if node.func.attr == "close":
            if {name for name, owner in ports.items() if owner == sock} & _loads(rest):
                found.append(node.lineno)
        elif node.func.attr == "bind" and node.args:
            address = node.args[0]
            others = {name for name, owner in ports.items() if owner != sock}
            if others & _loads([ast.Expr(address)]) or _port_reads(address) - {sock}:
                found.append(node.lineno)
    return found


def _closed_then_used(body: list[ast.stmt], ports: dict[str, str]) -> list[int]:
    """Lines where a socket's port outlives the socket in ``body``: returned
    from inside its ``with``, used after its ``with`` or after its
    ``close()``, or bound by a second socket. ``ports`` maps names holding a
    port to the socket it was read from."""
    found: list[int] = []
    ports = dict(ports)
    for index, statement in enumerate(body):
        rest = body[index + 1 :]
        if isinstance(statement, ast.With) and _with_frees(statement, rest):
            found.append(statement.lineno)
        if isinstance(statement, ast.Expr | ast.Assign):
            found += _calls_free(statement, rest, ports)
        if isinstance(statement, ast.Assign):
            names = [target.id for target in statement.targets if isinstance(target, ast.Name)]
            ports |= {name: sock for sock in _port_reads(statement.value) for name in names}
        for block in _blocks(statement):
            found += _closed_then_used(block, ports)
    return found


def _violations(source: str) -> list[int]:
    return sorted(set(_closed_then_used(ast.parse(source).body, {})))


def test_the_ban_catches_each_shape_of_the_race() -> None:
    probe_returned = """
def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
"""
    used_after_with = """
def f():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    connect(port)
"""
    used_after_close = """
def f():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    connect(port)
"""
    bound_twice = """
def f():
    udp.bind(("127.0.0.1", 0))
    port = udp.getsockname()[1]
    tcp.bind(("127.0.0.1", port))
"""
    for source in (probe_returned, used_after_with, used_after_close, bound_twice):
        assert _violations(source), source


def test_the_ban_allows_a_port_used_while_its_socket_is_open() -> None:
    held = """
def f():
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    port = silent.getsockname()[1]
    connect(port)
    silent.close()

@pytest.fixture
def g():
    with socket.create_server(("127.0.0.1", 0)) as listener:
        yield listener.getsockname()[1]
"""
    assert _violations(held) == []


def test_no_test_picks_a_port_and_frees_it_before_use() -> None:
    """Use ``tests/_ports.py``: its sockets hold each port while it is used."""
    offenders = [
        f"{path.relative_to(_TESTS)}:{line}"
        for path in sorted(_TESTS.rglob("*.py"))
        if path.name != "_ports.py"
        for line in _violations(path.read_text())
    ]
    assert offenders == []
