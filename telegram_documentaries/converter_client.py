"""ADK-backed Gemini image client used by the Converter.

Wraps a Google ADK ``LlmAgent`` running ``gemini-3.1-flash-image`` as multimodal
fusion: image bytes + dossier context in, hybrid portrait out. Inspected against
google-adk 2.11.0 — session-service calls are async, so the synchronous
``convert`` drives them with ``asyncio.run``; the ADK model caches its client
per event loop, so we inject ``GEMINI_API_KEY`` via ``client_kwargs`` rather
than constructing a loop-bound client ourselves.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from telegram_documentaries.converter import CONVERTER_INSTRUCTION, ConverterOutput

logger = logging.getLogger(__name__)

CONVERTER_MODEL = "gemini-3.1-flash-image"
CONVERTER_AGENT_NAME = "converter"
CONVERTER_APP_NAME = "telegram_documentaries"
CONVERTER_USER_ID = "converter"

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 2.0  # seconds
MAX_DELAY = 60.0  # seconds

#: Per-call task — the persona lives in CONVERTER_INSTRUCTION; the image and
#: dossier context travel in the message.
CONVERTER_TASK = (
    "Here is the human portrait and the behavioural dossier. "
    "Fuse the subject's likeness with an animal archetype that reflects their "
    "quirks into a single hybrid portrait. Return the rendered image as "
    "base64-encoded bytes in the structured output."
)


class ConverterQuotaExhaustedError(RuntimeError):
    """Raised when API quota is exhausted and retry won't help."""
    pass


class GeminiConverterClient:
    """Runs the Converter agent against ``gemini-3.1-flash-image`` through ADK."""

    def __init__(self, api_key: str, model: str = CONVERTER_MODEL) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY must not be empty")
        agent = LlmAgent(
            name=CONVERTER_AGENT_NAME,
            model=Gemini(model=model, client_kwargs={"api_key": api_key}),
            instruction=CONVERTER_INSTRUCTION,
            output_schema=ConverterOutput,
        )
        self._runner = InMemoryRunner(agent=agent, app_name=CONVERTER_APP_NAME)

    def convert(self, image: bytes, dossier_context: str) -> str:
        """Return the model's raw structured output for one image + dossier."""
        return asyncio.run(self._convert_async(image, dossier_context))

    async def _convert_async(self, image: bytes, dossier_context: str) -> str:
        message = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=image, mime_type="image/jpeg"),
                types.Part(text=f"{CONVERTER_TASK}\n\nDossier:\n{dossier_context}"),
            ],
        )
        session = await self._runner.session_service.create_session(
            app_name=CONVERTER_APP_NAME, user_id=CONVERTER_USER_ID
        )
        try:
            return await self._run_with_retry(session, message)
        finally:
            await self._runner.session_service.delete_session(
                app_name=CONVERTER_APP_NAME,
                user_id=CONVERTER_USER_ID,
                session_id=session.id,
            )

    async def _run_with_retry(self, session, message) -> str:
        """Run the converter with exponential backoff retry."""
        delay = BASE_DELAY
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                final_text: str | None = None
                async for event in self._runner.run_async(
                    user_id=CONVERTER_USER_ID,
                    session_id=session.id,
                    new_message=message,
                ):
                    if event.is_final_response() and event.content and event.content.parts:
                        final_text = event.content.parts[0].text or ""
                if final_text is None:
                    raise RuntimeError("Converter agent produced no final response")
                return final_text

            except Exception as e:
                last_error = e
                error_msg = str(e).lower()

                # Check if it's a quota exhaustion error (429)
                if "429" in error_msg or "resource_exhausted" in error_msg or "quota" in error_msg:
                    if attempt < MAX_RETRIES:
                        logger.warning(
                            f"Converter quota exceeded (attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                            f"retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, MAX_DELAY)  # Exponential backoff
                        continue
                    else:
                        logger.error("Converter quota exhausted after all retries")
                        raise ConverterQuotaExhaustedError(
                            "API quota exhausted for gemini-3.1-flash-image. "
                            "Please check your quota limits or upgrade to a paid tier. "
                            "See https://ai.google.dev/gemini-api/docs/rate-limits"
                        ) from e

                # For other errors, retry with backoff
                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"Converter error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}, "
                        f"retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, MAX_DELAY)
                    continue
                else:
                    logger.error(f"Converter failed after {MAX_RETRIES + 1} attempts: {e}")
                    raise

        # Should not reach here
        raise last_error
