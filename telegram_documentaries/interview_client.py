"""ADK-backed Gemini interview client used by the Interviewer.

Two ADK ``LlmAgent``s on ``gemini-3.1-flash-lite`` — one that asks the next
question, one that synthesises the completed dossier — each bound to its own
structured output schema (``NextQuestion`` / ``InterviewProfile``), so both
methods return the model's raw structured output for the Interviewer to parse
at the edge. Same shape as ``vision.py``: session services are async, so the
synchronous protocol methods drive them with ``asyncio.run``; the ADK model
caches its client per event loop, so ``GEMINI_API_KEY`` is injected via
``client_kwargs``. The persona lives in ``INTERVIEW_INSTRUCTION``; the per-call
task and the accumulated Q&A travel in the message.

Timeout configuration: ``DEFAULT_GEMINI_TIMEOUT = 60.0`` seconds. The
``timeout`` parameter wraps the ADK runner drain in ``asyncio.wait_for``;
on timeout, ``InterviewerError`` is raised.
"""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from telegram_documentaries.interviewer import (
    INTERVIEW_INSTRUCTION,
    InterviewerError,
    InterviewProfile,
    NextQuestion,
)

INTERVIEW_MODEL = "gemini-3.1-flash-lite"
INTERVIEW_APP_NAME = "telegram_documentaries"
QUESTION_AGENT_NAME = "questioner"
PROFILE_AGENT_NAME = "profiler"
INTERVIEW_USER_ID = "interviewer"

#: Default timeout for Gemini API calls (seconds).
DEFAULT_GEMINI_TIMEOUT = 60.0

#: Per-call tasks (persona + accumulated Q&A arrive with the message).
QUESTION_TASK = (
    "Ask the next question of this field interview. Interview so far:\n{context}\n"
    "If there are no answers yet, ask the opening question."
)
PROFILE_TASK = (
    "The interview is over. Distil it into the structured behavioural profile "
    "and the single animal the subject most resembles. Interview:\n{context}"
)


class GeminiInterviewClient:
    """Runs the Interviewer's agents against ``gemini-3.1-flash-lite`` through ADK."""

    def __init__(
        self, api_key: str, model: str = INTERVIEW_MODEL, timeout: float = DEFAULT_GEMINI_TIMEOUT
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY must not be empty")
        self._timeout = timeout
        self._question_runner = self._build_runner(
            api_key, model, QUESTION_AGENT_NAME, NextQuestion
        )
        self._profile_runner = self._build_runner(
            api_key, model, PROFILE_AGENT_NAME, InterviewProfile
        )

    @staticmethod
    def _build_runner(
        api_key: str, model: str, agent_name: str, schema: type[NextQuestion | InterviewProfile]
    ) -> InMemoryRunner:
        agent = LlmAgent(
            name=agent_name,
            model=Gemini(model=model, client_kwargs={"api_key": api_key}),
            instruction=INTERVIEW_INSTRUCTION,
            output_schema=schema,
        )
        return InMemoryRunner(agent=agent, app_name=INTERVIEW_APP_NAME)

    def generate_question(self, context: str) -> str:
        """The model's raw structured next question for the accumulated Q&A."""
        prompt = QUESTION_TASK.format(context=context)
        return asyncio.run(self._run_async(self._question_runner, QUESTION_AGENT_NAME, prompt))

    def synthesize_profile(self, context: str) -> str:
        """The model's raw structured profile synthesis for the finished interview."""
        prompt = PROFILE_TASK.format(context=context)
        return asyncio.run(self._run_async(self._profile_runner, PROFILE_AGENT_NAME, prompt))

    async def _run_async(self, runner: InMemoryRunner, agent_name: str, prompt: str) -> str:
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        session = await runner.session_service.create_session(
            app_name=INTERVIEW_APP_NAME, user_id=INTERVIEW_USER_ID
        )
        try:
            # Drain the runner to completion rather than returning from inside
            # the loop: an early return cancels the ADK run mid-flight and logs
            # cancellation/context-detach tracebacks.
            final_text: str | None = None

            async def _drain() -> None:
                nonlocal final_text
                async for event in runner.run_async(
                    user_id=INTERVIEW_USER_ID,
                    session_id=session.id,
                    new_message=message,
                ):
                    if event.is_final_response() and event.content and event.content.parts:
                        final_text = event.content.parts[0].text or ""

            await asyncio.wait_for(_drain(), timeout=self._timeout)

            if final_text is None:
                raise RuntimeError(f"{agent_name} agent produced no final response")
            return final_text
        except TimeoutError as exc:
            raise InterviewerError("model timeout") from exc
        finally:
            await runner.session_service.delete_session(
                app_name=INTERVIEW_APP_NAME,
                user_id=INTERVIEW_USER_ID,
                session_id=session.id,
            )
