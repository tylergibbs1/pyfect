"""The ASGI 3 interface (asgiref's ``Scope``, ``Receive``, ``Send`` and
``ASGI3Application``), loosely typed as servers send it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

type Scope = MutableMapping[str, Any]
type Message = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[Message]]
type Send = Callable[[Message], Awaitable[None]]
type AsgiApplication = Callable[[Scope, Receive, Send], Awaitable[None]]
