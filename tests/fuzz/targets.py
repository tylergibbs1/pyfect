"""Every fuzz target, by name."""

from . import codec_targets, http_targets, jose_targets, schema_targets, server_target, text_targets
from ._harness import TARGETS, Target

MODULES = (
    codec_targets,
    http_targets,
    jose_targets,
    schema_targets,
    server_target,
    text_targets,
)

__all__ = ["MODULES", "TARGETS", "Target"]
