"""Entrypoint: `python -m telegram_documentaries`."""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from telegram_documentaries.bot import Bot
from telegram_documentaries.client import TelegramClient
from telegram_documentaries.logutil import configure_logging

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def main() -> int:
    load_dotenv()
    configure_logging(verbose=os.environ.get("DEBUG", "").strip().lower() in _TRUE)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and fill it in.")
        return 1

    # GEMINI_API_KEY is only needed from Phase 2 (Bouncer) onward.
    logger.info("starting gateway as @%s", os.environ.get("BOT_USERNAME", "unknown"))

    try:
        Bot(TelegramClient(token=token)).run()
    except KeyboardInterrupt:
        logger.info("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
