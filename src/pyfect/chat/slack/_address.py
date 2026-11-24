"""Slack addresses: ``{team}/{channel}`` or ``{team}/{channel}/{thread_ts}``."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.chat import chat_thread
from pyfect.chat.chat_thread import ChatThread

PLATFORM = "slack"


@dataclass(frozen=True)
class Parts:
    """The parts of a Slack address."""

    team: str
    channel: str
    thread_ts: str | None = None


def thread(parts: Parts) -> ChatThread:
    """The address of ``parts``."""
    suffix = "" if parts.thread_ts is None else f"/{parts.thread_ts}"
    return chat_thread.make(PLATFORM, f"{parts.team}/{parts.channel}{suffix}")


def parts(address: ChatThread) -> Parts | None:
    """The parts of a Slack address, or ``None`` for any other."""
    if address.platform != PLATFORM:
        return None
    segments = address.id.split("/")
    if not 2 <= len(segments) <= 3 or any(segment == "" for segment in segments):
        return None
    return Parts(*segments)


def is_direct_channel(channel: str) -> bool:
    """Whether ``channel`` is a direct conversation."""
    return channel.startswith("D")


def _seconds(text: str) -> float:
    try:
        return float(text) if text.strip() else 0.0
    except ValueError:
        return float("nan")


def compare_ts(a: str, b: str) -> int:
    """Compares two Slack ``ts`` values in time order."""
    a_seconds, _, a_micros = a.partition(".")
    b_seconds, _, b_micros = b.partition(".")
    seconds = _seconds(a_seconds) - _seconds(b_seconds)
    if seconds != 0:
        return -1 if seconds < 0 else 1
    width = max(len(a_micros), len(b_micros))
    left, right = a_micros.ljust(width, "0"), b_micros.ljust(width, "0")
    return -1 if left < right else 1 if left > right else 0
