"""``SchemaError``: the error the decoders and encoders fail with."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.errors import TaggedError
from pyfect.schema.issue import Issue, format_issue


@dataclass(eq=False)
class SchemaError(TaggedError):
    """A value did not match a schema. ``issue`` says why and where;
    ``message`` (also ``str(error)``) is the issue in Effect's default
    format."""

    issue: Issue

    @property
    def message(self) -> str:
        return format_issue(self.issue)
