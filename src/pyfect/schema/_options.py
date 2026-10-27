"""Parse options (Effect's ``SchemaAST.ParseOptions``), passed as keyword
arguments to the decoders and encoders."""

from __future__ import annotations

from typing import Literal, TypedDict

from pyfect._concurrency import Concurrency


class ParseOptions(TypedDict, total=False):
    """How parsing behaves. Options given when a decoder is made apply to
    each call; options given to a call override them key by key.

    - ``errors``: ``"first"`` (default) stops at the first issue, ``"all"``
      collects every one.
    - ``on_excess_property``: ``"ignore"`` (default) drops keys a struct
      does not declare, ``"error"`` rejects them.
    - ``disable_checks``: skip checks, still applying defaults and
      transformations.
    - ``concurrency``: how many children of a product parse at once (as
      ``fx.for_each``); sequential by default.
    - ``report_input``: keep rejected values in issues and print them
      (``Expected string, got 1``). They may hold secrets.
    """

    errors: Literal["first", "all"]
    on_excess_property: Literal["ignore", "error"]
    disable_checks: bool
    concurrency: Concurrency
    report_input: bool
