"""Long polling with ``getUpdates`` (Effect's ``internal/polling.ts``)."""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect.chat.chat_error import ChatError, InvalidRequest
from pyfect.chat.telegram import _errors, _json
from pyfect.chat.telegram._receive import ALLOWED_UPDATES, Outcome
from pyfect.chat.telegram.telegram_bot_api import TelegramBotApiService
from pyfect.duration import Duration, seconds
from pyfect.result import Ok

LOGGED_SKIPPED = "telegram polling: an update was not accepted, skipped"
LOGGED_CONFLICT = (
    "telegram polling: getUpdates answered 409, another poller or a webhook is active;"
    " polling stopped"
)
LOGGED_RETRYING = "telegram polling: getUpdates failed, retrying"

_RETRY_AFTER = seconds(5)


@dataclass(frozen=True, kw_only=True)
class Options:
    api: TelegramBotApiService
    timeout: Duration
    max_attempts: int
    receive: Callable[[object], Effect[Outcome]]


def _is_conflict(error: ChatError) -> bool:
    reason = error.reason
    return isinstance(reason, InvalidRequest) and reason.detail == "conflict"


def get_updates(
    api: TelegramBotApiService, offset: int | None, timeout: Duration
) -> Effect[list[object], ChatError]:
    """One ``getUpdates``, from ``offset``."""
    params: dict[str, object] = {
        "offset": offset,
        "timeout": int(timeout.to_millis() // 1000),
        "allowed_updates": list(ALLOWED_UPDATES),
    }
    return api.call("getUpdates", params).map(_json.as_list)


def run_update(update: object, options: Options) -> Effect[None]:
    """Runs one update, retrying ``notAccepted`` and ``invalid`` up to
    ``max_attempts`` times with a backoff from one second. Then it is logged
    and skipped: ``getUpdates`` is one ordered queue, and retrying forever
    would stall every chat."""

    @fx.gen
    def body() -> Generator[Effect[Any, Never, Any], Any]:
        attempt = 1
        while True:
            outcome = yield from options.receive(update)
            if outcome in ("accepted", "unhandled"):
                return
            if attempt >= options.max_attempts:
                yield from fx.log_error(LOGGED_SKIPPED).annotate_logs(
                    {"telegram.update_id": _json.integer(update, "update_id")}
                )
                return
            yield from fx.sleep(seconds(2 ** (attempt - 1)))
            attempt += 1

    return body


def loop(first: Sequence[object], options: Options) -> Effect[None]:
    """The polling loop. ``first`` is the answer of the call the layer made
    itself. Each update's offset is confirmed by the next call only once the
    update ran, so a process that dies part way sees it again."""

    @fx.gen
    def body() -> Generator[Effect[Any, Never, Any], Any]:
        batch: Sequence[object] = first
        offset: int | None = None
        while True:
            for update in batch:
                yield from run_update(update, options)
                id = _json.integer(update, "update_id")
                if id is not None:
                    offset = id + 1
            answer = yield from get_updates(options.api, offset, options.timeout).result()
            if isinstance(answer, Ok):
                batch = answer.value
                continue
            batch = []
            error: ChatError = answer.error
            if _is_conflict(error):
                yield from fx.log_error(LOGGED_CONFLICT)
                return
            yield from fx.log_warning(LOGGED_RETRYING).annotate_logs(
                {"chat.error.reason": type(error.reason).__name__}
            )
            yield from fx.sleep(_RETRY_AFTER)

    return body


def conflict(error: ChatError) -> ChatError:
    """The error the layer fails with on a 409 at start."""
    if _is_conflict(error):
        return _errors.chat_error("layerPolling", _errors.invalid_request("conflict"))
    return error
