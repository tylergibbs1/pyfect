"""Every cross-run case, by family."""

from . import cases_collections, cases_core, cases_fibers, cases_pubsub, cases_resources

CASES = [
    *cases_core.CASES,
    *cases_pubsub.CASES,
    *cases_resources.CASES,
    *cases_fibers.CASES,
    *cases_collections.CASES,
]
