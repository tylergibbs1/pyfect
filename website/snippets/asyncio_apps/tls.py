import datetime
import ipaddress
import ssl
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import pyfect as fx
from pyfect.http import httpx_client, hypercorn_server, router, server_response, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http.server import HttpServer
from pyfect.net.net_address import UnixPathAddress


def self_signed(directory: Path) -> tuple[str, str]:
    """A certificate for 127.0.0.1 and its key, as PEM files (use real ones in production)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(ski, critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    certfile, keyfile = directory / "cert.pem", directory / "key.pem"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(certfile), str(keyfile)


@fx.fn
def get_over_tls(engine: str):
    server = yield from HttpServer()
    http = yield from HttpClient()
    address = server.address
    assert not isinstance(address, UnixPathAddress)
    response = yield from http.get(f"https://127.0.0.1:{address.port}/")
    print(engine, response.status, (yield from response.text))


App = router.serve(
    router.add("GET", "/", server_response.text("over TLS")),
    disable_logger=True,
    disable_listen_log=True,
)

with tempfile.TemporaryDirectory() as directory:
    certfile, keyfile = self_signed(Path(directory))
    # hypercorn's config takes hypercorn.Config attributes: certfile and keyfile.
    hypercorn_tls = hypercorn_server.layer(
        host="127.0.0.1", config={"certfile": certfile, "keyfile": keyfile}
    )
    # uvicorn's takes uvicorn.Config arguments, named differently: ssl_certfile and ssl_keyfile.
    uvicorn_tls = uvicorn_server.layer(
        host="127.0.0.1", config={"ssl_certfile": certfile, "ssl_keyfile": keyfile}
    )
    # A client that trusts the self-signed certificate, closed before the server stops.
    trusting = httpx_client.layer_with(verify=ssl.create_default_context(cafile=certfile))
    for engine, served_on in (("hypercorn", hypercorn_tls), ("uvicorn", uvicorn_tls)):
        program = get_over_tls(engine).pipe(fx.provide(trusting))
        fx.run_main(program.pipe(fx.provide(App)).pipe(fx.provide(served_on)))
