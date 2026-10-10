"""ADK-backed Gemini script client used by the Scripter.

Wraps a Google ADK ``LlmAgent`` running ``gemini-3.1-flash-lite`` — the same
model as the Bouncer and the Interviewer — bound to the structured output schema
``ScripterOutput``, so ``generate_script`` returns the model's raw structured
output for the Scripter to parse at the edge. Same shape as
``interview_client.py``: session services are async, so the synchronous protocol
method drives them with ``asyncio.run``; the ADK model caches its client per
event loop, so ``GEMINI_API_KEY`` is injected via ``client_kwargs``. The persona
lives in ``SCRIPTER_INSTRUCTION``; the completed dossier travels in the message.
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from telegram_documentaries.scripter import SCRIPTER_INSTRUCTION, ScripterOutput

SCRIPTER_MODEL = "gemini-3.1-flash-lite"
SCRIPTER_AGENT_NAME = "scripter"
SCRIPTER_APP_NAME = "telegram_documentaries"
SCRIPTER_USER_ID = "scripter"

#: Per-call task (the persona arrives in ``SCRIPTER_INSTRUCTION``; the completed
#: dossier arrives with the message).
SCRIPT_TASK = (
    "Here is the completed dossier for one human subject. Narrate their story "
    "as a single paragraph of wonder-struck nature-documentary prose, at most "
    "90 words, no markdown.\n\nDossier:\n{context}"
)


class GeminiScripterClient:
    """Runs the Scripter agent against ``gemini-3.1-flash-lite`` through ADK."""

    def __init__(self, api_key: str, model: str = SCRIPTER_MODEL) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY must not be empty")
        agent = LlmAgent(
            name=SCRIPTER_AGENT_NAME,
            model=Gemini(model=model, client_kwargs={"api_key": api_key}),
            instruction=SCRIPTER_INSTRUCTION,
            output_schema=ScripterOutput,
        )
        self._runner = InMemoryRunner(agent=agent, app_name=SCRIPTER_APP_NAME)

    def generate_script(self, dossier_context: str) -> str:
        """The model's raw structured narration for one completed dossier."""
        prompt = SCRIPT_TASK.format(context=dossier_context)
        return asyncio.run(self._run_async(prompt))

    async def _run_async(self, prompt: str) -> str:
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        session = await self._runner.session_service.create_session(
            app_name=SCRIPTER_APP_NAME, user_id=SCRIPTER_USER_ID
        )
        try:
            # Drain the runner to completion rather than returning from inside
            # the loop: an early return cancels the ADK run mid-flight and logs
            # cancellation/context-detach tracebacks.
            final_text: str | None = None
            async for event in self._runner.run_async(
                user_id=SCRIPTER_USER_ID,
                session_id=session.id,
                new_message=message,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    final_text = event.content.parts[0].text or ""
            if final_text is None:
                raise RuntimeError("scripter agent produced no final response")
            return final_text
        finally:
            await self._runner.session_service.delete_session(
                app_name=SCRIPTER_APP_NAME,
                user_id=SCRIPTER_USER_ID,
                session_id=session.id,
            )
