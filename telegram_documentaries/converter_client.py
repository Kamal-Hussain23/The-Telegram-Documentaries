"""ADK-backed Gemini image client used by the Converter.

Wraps a Google ADK ``LlmAgent`` running ``gemini-3.1-flash-image`` as multimodal
image generation: image bytes + text prompt in, structured output with generated
image bytes out. Inspected against google-adk 2.11.0 — session-service calls are
async, so the synchronous ``generate_image`` drives them with ``asyncio.run``;
the ADK model caches its client per event loop, so we inject ``GEMINI_API_KEY``
via ``client_kwargs`` rather than constructing a loop-bound client ourselves.

The ``gemini-3.1-flash-image`` model returns the generated image as an
``inline_data`` part (binary), not as JSON text. The ADK's ``output_schema``
is for structured text output, so we extract the image from the response parts
and wrap it in the expected JSON format for the ``parse_output`` validator.

Timeout configuration: ``DEFAULT_GEMINI_TIMEOUT = 60.0`` seconds. The
``timeout`` parameter wraps the ADK runner drain in ``asyncio.wait_for``;
on timeout, ``ConverterError`` is raised.
"""

from __future__ import annotations

import asyncio
import base64
import json

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from telegram_documentaries.converter import CONVERTER_INSTRUCTION, ConverterError

CONVERTER_MODEL = "gemini-3.1-flash-image"
CONVERTER_AGENT_NAME = "converter"
CONVERTER_APP_NAME = "telegram_documentaries"
CONVERTER_USER_ID = "converter"

#: Default timeout for Gemini API calls (seconds).
DEFAULT_GEMINI_TIMEOUT = 60.0


class GeminiConverterClient:
    """Runs the Converter agent against ``gemini-3.1-flash-image`` through ADK."""

    def __init__(
        self, api_key: str, model: str = CONVERTER_MODEL, timeout: float = DEFAULT_GEMINI_TIMEOUT
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY must not be empty")
        self._timeout = timeout
        agent = LlmAgent(
            name=CONVERTER_AGENT_NAME,
            model=Gemini(model=model, client_kwargs={"api_key": api_key}),
            instruction=CONVERTER_INSTRUCTION,
            # output_schema=ConverterOutput,  # Image model returns inline_data, not JSON
        )
        self._runner = InMemoryRunner(agent=agent, app_name=CONVERTER_APP_NAME)

    def generate_image(self, photo_bytes: bytes, dossier_context: str) -> str:
        """Return the model's raw structured output for one photo + dossier."""
        return asyncio.run(self._generate_async(photo_bytes, dossier_context))

    async def _generate_async(self, photo_bytes: bytes, dossier_context: str) -> str:
        message = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg"),
                types.Part(text=dossier_context),
            ],
        )
        session = await self._runner.session_service.create_session(
            app_name=CONVERTER_APP_NAME, user_id=CONVERTER_USER_ID
        )
        try:
            # Drain the runner to completion rather than returning from inside
            # the loop: an early return cancels the ADK run mid-flight and logs
            # cancellation/context-detach tracebacks.
            final_image_bytes: bytes | None = None

            async def _drain() -> None:
                nonlocal final_image_bytes
                async for event in self._runner.run_async(
                    user_id=CONVERTER_USER_ID,
                    session_id=session.id,
                    new_message=message,
                ):
                    if event.is_final_response() and event.content and event.content.parts:
                        # The image model returns the generated image as inline_data.
                        # Find the part with inline_data (image bytes).
                        for part in event.content.parts:
                            if part.inline_data is not None and part.inline_data.data:
                                final_image_bytes = part.inline_data.data
                                break

            await asyncio.wait_for(_drain(), timeout=self._timeout)

            if final_image_bytes is None:
                raise RuntimeError("converter agent produced no image data")
            # Wrap the image bytes in the expected JSON format for parse_output.
            return json.dumps({"image_bytes": base64.b64encode(final_image_bytes).decode("ascii")})
        except TimeoutError as exc:
            raise ConverterError("model timeout") from exc
        finally:
            await self._runner.session_service.delete_session(
                app_name=CONVERTER_APP_NAME,
                user_id=CONVERTER_USER_ID,
                session_id=session.id,
            )
