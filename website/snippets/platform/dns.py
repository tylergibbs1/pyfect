import pyfect as fx
from pyfect.net import address_resolver, dns
from pyfect.net.address_resolver import AddressResolver
from pyfect.net.dns import Dns, DnsError
from pyfect.net.host import DomainName

# A fixed zone, so the example needs no network. In production, provide
# `dns.layer_system()`, which asks the operating system's resolver.
Zone = dns.layer_static(
    hosts={"api.internal": ["10.0.0.7", "10.0.0.8", "fd00::7"]},
    records={"example.com": [dns.Mx(DomainName("mail.example.com"), 10)]},
)


@fx.fn
def program():
    names = yield from Dns()
    ipv4 = yield from names.lookup("api.internal", family="IPv4")
    print("lookup", [str(address) for address in ipv4])
    print("mx", (yield from names.resolve("example.com", dns.Mx)))
    print("reverse", (yield from names.reverse("10.0.0.7")))

    resolver = yield from AddressResolver()
    for target in ("api.internal:8080", "[fd00::1]:443", "127.0.0.1:5432"):
        addresses = yield from resolver.resolve(target)
        print(target, "->", [str(address) for address in addresses])

    missing = yield from resolver.resolve("nowhere.internal:80").flip()
    assert isinstance(missing, DnsError)
    print(missing.reason, missing.message)


fx.run_main(program().pipe(fx.provide(address_resolver.layer().pipe(fx.layer.provide_merge(Zone)))))
