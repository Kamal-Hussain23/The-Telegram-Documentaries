"""Entrypoint: `python -m telegram_documentaries`."""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from telegram_documentaries.bot import Bot
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.client import TelegramClient
from telegram_documentaries.logutil import configure_logging
from telegram_documentaries.state import StateDriver
from telegram_documentaries.vision import GeminiVisionClient

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def main() -> int:
    load_dotenv()
    configure_logging(verbose=os.environ.get("DEBUG", "").strip().lower() in _TRUE)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and fill it in.")
        return 1

    # GEMINI_API_KEY is read from .env only (requirements decision 2); the
    # Bouncer is the first stage that needs it.
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("GEMINI_API_KEY is missing. Copy .env.example to .env and fill it in.")
        return 1

    logger.info("starting gateway as @%s", os.environ.get("BOT_USERNAME", "unknown"))

    bouncer = Bouncer(GeminiVisionClient(api_key=api_key))
    try:
        Bot(TelegramClient(token=token), bouncer=bouncer, state=StateDriver()).run()
    except KeyboardInterrupt:
        logger.info("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
