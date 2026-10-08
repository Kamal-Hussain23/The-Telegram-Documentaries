"""Logging helpers.

TECH.md: prefer decorators for entering/exiting/timing a call over sprinkling
log statements through business logic.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from telegram_documentaries.models import Message

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)

#: Longest message text written to the log before it is truncated.
MAX_LOGGED_TEXT = 120


def describe_message(message: Message) -> str:
    """One-line summary of an inbound message: who sent it, and what it was.

    Non-text payloads (photos, stickers, voice notes) are summarised as
    `media` rather than logged as `text=None`.
    """
    if message.text is None:
        return f"chat_id={message.chat.id} media"
    text = message.text
    if len(text) > MAX_LOGGED_TEXT:
        text = text[:MAX_LOGGED_TEXT] + "…"
    return f"chat_id={message.chat.id} text={text!r}"


def log_call(func: Callable[P, R]) -> Callable[P, R]:
    """Log entry, exit, duration, and any exception raised by `func`."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        name = f"{func.__module__}.{func.__qualname__}"
        started = time.monotonic()
        logger.debug("enter %s", name)
        try:
            result = func(*args, **kwargs)
        except Exception:
            logger.exception("error %s after %.0fms", name, (time.monotonic() - started) * 1000)
            raise
        logger.debug("exit %s in %.0fms", name, (time.monotonic() - started) * 1000)
        return result

    return wrapper


def configure_logging(verbose: bool = False) -> None:
    """Structured, single-line logs on stderr."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    # httpx (requests' neighbour in some stacks) is chatty at DEBUG.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
