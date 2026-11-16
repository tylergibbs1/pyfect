"""The cluster workflow engine turns a storage failure into a defect only where
Effect's ``ClusterWorkflowEngine`` does (``Effect.orDie``). Anywhere else a
transient ``PersistenceError`` must go through ``_retry_persistence`` (unbounded)
or ``_retry_persistence_bounded``: a defect inside a workflow is stored as its
result, so an outage would fail it for good (Effect #10206, #10311, #10356).

A new ``.or_die()`` in the engine fails here. Use a retry helper, or add the
site with the Effect ``orDie`` it mirrors."""

import ast
from collections import Counter

import _source

ENGINE = _source.SRC / "cluster" / "cluster_workflow_engine"

# enclosing function -> Effect's site, for each ``.or_die()`` in the package.
EXPECTED: dict[str, str] = {
    "ensure_success": "ensureSuccess: Effect.orDie after the abandon re-raise",
    "_retry_persistence_bounded": "retryPersistenceBounded",
    "_retry_persistence": "retryPersistence",
    "ClusterEngine.send_discard.body": "sendDiscard: Effect.orDie(Effect.currentSpan)",
    "ClusterEngine.reset_activity_attempt": "resetActivityAttempt: retry 3 times, then orDie",
    "ClusterEngine.interrupt_unsafe.body": "interruptUnsafe: orDie(sharding.sendOutgoing)",
    "ClusterEngine._load_activation": "register: orDie(requestReply(InterruptSignal))",
    "ClusterEngine.execute": "execute: parent ? retryPersistence : orDie (top-level calls)",
    "ClusterEngine.poll": "poll: Effect.orDie",
}


# enclosing function -> why it may give up after a few tries.
BOUNDED: dict[str, str] = {
    "ClusterEngine.interrupt": "interrupt: retryPersistenceBounded",
    "ClusterEngine.deferred_result": "uninterruptible exit cleanup reads the interrupt signal",
}


def _call_sites(name: str) -> Counter[str]:
    sites: Counter[str] = Counter()
    for path in _source.files(ENGINE, recursive=False):
        tree = _source.tree(path)

        def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(child, (*scope, child.name))
                    continue
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == name
                ) or (isinstance(child, ast.Name) and child.id == name):
                    sites[".".join(scope)] += 1
                visit(child, scope)

        visit(tree, ())
    return sites


def test_storage_failures_die_only_where_effect_dies() -> None:
    sites = _call_sites("or_die")
    unexpected = sorted(set(sites) - set(EXPECTED))
    assert not unexpected, (
        f"new .or_die() in the cluster workflow engine: {unexpected}. A storage failure "
        "there becomes the workflow's result; retry it with _retry_persistence, or add the "
        "site to EXPECTED with the Effect orDie it mirrors"
    )
    assert set(EXPECTED) <= set(sites), sorted(set(EXPECTED) - set(sites))


def test_only_interrupt_reads_give_up_after_a_few_tries() -> None:
    sites = _call_sites("_retry_persistence_bounded")
    assert set(sites) == set(BOUNDED), (
        "a bounded retry dies after a short outage; only the interrupt reads made by "
        f"uninterruptible cleanup use it: {sorted(sites)}"
    )
