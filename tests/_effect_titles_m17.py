# ruff: noqa: E501 (Effect test titles, kept whole so they match)
"""Effect 4.1.2 test titles not ported yet (milestone M17, the move from Effect 4.0.6).

Each M17 agent ports the titles of its area and deletes them here; an empty file closes the
milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M17_REASON = "NOT_PORTED new in Effect 4.1.2 (milestone M17), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {}
