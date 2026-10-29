"""Escaping for the documentation pages (Effect's ``internal/html``)."""

import json
from collections.abc import Callable
from importlib import resources


def escape_json(value: object) -> str:
    """``value`` as JSON safe inside a ``<script>`` element."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_attribute(text: str) -> str:
    return escape(text).replace('"', "&quot;").replace("'", "&#39;")


def memoize_success[A](make: Callable[[], A]) -> Callable[[], A]:
    """``make()``, made once it succeeds: a raise is retried on the next
    call (Effect's ``Function.memoize`` of a function that throws)."""
    done: list[A] = []

    def get() -> A:
        if not done:
            done.append(make())
        return done[0]

    return get


def asset(name: str) -> str:
    """A bundled documentation asset (``_assets/<name>``)."""
    return resources.files("pyfect.http_api").joinpath("_assets", name).read_text("utf-8")
