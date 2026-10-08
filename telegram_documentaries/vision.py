"""ADK-backed Gemini vision client used by the Bouncer.

Wraps a Google ADK ``LlmAgent`` running ``gemini-3.1-flash-lite`` as multimodal
classification: image bytes in, structured verdict JSON out. Inspected against
google-adk 2.11.0 — session-service calls are async, so the synchronous
``classify`` drives them with ``asyncio.run``; the ADK model caches its client
per event loop, so we inject ``GEMINI_API_KEY`` via ``client_kwargs`` rather
than constructing a loop-bound client ourselves.
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from telegram_documentaries.bouncer import BOUNCER_INSTRUCTION, BouncerVerdict

BOUNCER_MODEL = "gemini-3.1-flash-lite"
BOUNCER_AGENT_NAME = "bouncer"
BOUNCER_APP_NAME = "telegram_documentaries"
BOUNCER_USER_ID = "bouncer"


class GeminiVisionClient:
    """Runs the Bouncer agent against ``gemini-3.1-flash-lite`` through ADK."""

    def __init__(self, api_key: str, model: str = BOUNCER_MODEL) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY must not be empty")
        agent = LlmAgent(
            name=BOUNCER_AGENT_NAME,
            model=Gemini(model=model, client_kwargs={"api_key": api_key}),
            instruction=BOUNCER_INSTRUCTION,
            output_schema=BouncerVerdict,
        )
        self._runner = InMemoryRunner(agent=agent, app_name=BOUNCER_APP_NAME)

    def classify(self, image: bytes) -> str:
        """Return the model's raw structured verdict for one image."""
        return asyncio.run(self._classify_async(image))

    async def _classify_async(self, image: bytes) -> str:
        message = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=image, mime_type="image/jpeg"),
                types.Part(text="Report the structured verdict for this image."),
            ],
        )
        session = await self._runner.session_service.create_session(
            app_name=BOUNCER_APP_NAME, user_id=BOUNCER_USER_ID
        )
        try:
            # Drain the runner to completion rather than returning from inside
            # the loop: an early return cancels the ADK run mid-flight and logs
            # cancellation/context-detach tracebacks.
            final_text: str | None = None
            async for event in self._runner.run_async(
                user_id=BOUNCER_USER_ID,
                session_id=session.id,
                new_message=message,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    final_text = event.content.parts[0].text or ""
            if final_text is None:
                raise RuntimeError("Bouncer agent produced no final response")
            return final_text
        finally:
            await self._runner.session_service.delete_session(
                app_name=BOUNCER_APP_NAME,
                user_id=BOUNCER_USER_ID,
                session_id=session.id,
            )
