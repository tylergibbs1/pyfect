import pyfect as fx
from pyfect import layer
from pyfect.ai import mcp_client, mcp_protocol, mcp_server
from pyfect.http import live_server, router

# A skill is a SKILL.md with YAML frontmatter plus the files it refers to.
Refunds = mcp_server.skill(
    "skill://billing/refunds/SKILL.md",
    {
        "SKILL.md": "---\nname: refunds\ndescription: Process refunds\n---\n\n"
        "Read references/policy.md before issuing a refund.\n",
        "references/policy.md": "Refunds above CHF 500 need approval.\n",
    },
)

Server = Refunds.pipe(
    layer.provide_merge(
        mcp_server.layer_http(
            name="billing", version="1.0.0", path="/mcp", protocols=(mcp_protocol.v2026_07_28,)
        )
    )
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)


@fx.fn
def program():
    client = yield from mcp_client.McpClient()
    [refunds] = yield from client.list_skills()
    print(refunds["uri"], refunds["frontmatter"])
    children = yield from client.read_resource_directory("skill://billing/refunds")
    print([child["name"] for child in children])
    # The bytes are checked against the SHA-256 digest the skill listed.
    policy = yield from client.read_skill_resource(
        refunds, "skill://billing/refunds/references/policy.md"
    )
    print(policy["contents"][0].get("text"))


Client = mcp_client.layer_http(
    name="docs",
    version="1.0.0",
    url="/mcp",
    protocol=mcp_protocol.v2026_07_28,
    extensions={"skills": True},
)

fx.run_main(
    program()
    .pipe(fx.provide(Client))
    .pipe(fx.provide(Served))
    .pipe(fx.provide(live_server.layer_test()))
)
