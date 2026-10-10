"""The Converter: multimodal fusion of the original photo and the dossier into a hybrid portrait.

The first pipeline stage to use ``gemini-3.1-flash-image``. Its answer is a typed
contract (requirements decision 3): the model's structured output is parsed into
a Pydantic model and free text is never interpreted downstream. Logging is
decorator-based via ``log_call`` (decision 9) — no log statements in the
business logic.
"""

from __future__ import annotations

import base64
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from telegram_documentaries.logutil import log_call
from telegram_documentaries.state import Dossier, Phase, StateDriver

#: Sent when the Converter fails to generate a hybrid portrait. In-character,
#: cheeky, and explicit that we can retry.
CONVERTER_FAILURE_TEXT = (
    "Oh dear — the darkroom spirits are being temperamental and the hybrid "
    "refuses to develop. The dossier is safe, so send another photo when "
    "you're ready and we'll give it another go."
)

#: Instruction handed to the Gemini agent; the model reports the hybrid portrait
#: via the structured ``ConverterOutput`` output schema.
CONVERTER_INSTRUCTION = (
    "You are The Converter, the darkroom alchemist of a wildlife-documentary "
    "bot. You receive a human portrait and a behavioural dossier describing "
    "their quirks. Fuse the subject's likeness with an animal archetype that "
    "reflects those quirks — e.g., a caffeinated badger, a meticulous beaver, "
    "a midnight raccoon — into a single hybrid portrait. Return the rendered "
    "image as base64-encoded bytes in the structured output. English only."
)


class ConverterError(ValueError):
    """The model did not return a valid structured converter output."""


class ConverterOutput(BaseModel):
    """Typed, structured output from the Converter model. Never free text."""

    model_config = ConfigDict(extra="ignore")

    image_bytes: str  # base64-encoded image bytes
    confidence: float | None = None
    reason: str | None = None


class ConverterClient(Protocol):
    """The slice of the Gemini converter client the Converter depends on.

    The method returns the model's raw structured output for the edge parser;
    ``image`` and ``dossier_context`` travel in the prompt.
    """

    def convert(self, image: bytes, dossier_context: str) -> str: ...


def parse_output(raw: str) -> ConverterOutput:
    """Parse the model's structured output into a typed converter output.

    Anything that is not a JSON object matching the schema is raised as a
    ``ConverterError``; the public boundary (``Converter.convert``, decorated
    with ``log_call``) logs it loudly rather than silently dropping it.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConverterError(f"output is not valid JSON: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise ConverterError(f"output must be a JSON object: {raw!r}")
    try:
        output = ConverterOutput.model_validate(payload)
    except ValidationError as exc:
        raise ConverterError(f"output does not match schema: {raw!r}") from exc
    # Decode base64 image_bytes for internal use
    try:
        output.image_bytes = base64.b64decode(output.image_bytes)
    except Exception as exc:
        raise ConverterError(f"image_bytes is not valid base64: {raw!r}") from exc
    return output


def dossier_context(dossier: Dossier) -> str:
    """The completed dossier as text, so the model can adapt to it."""
    lines: list[str] = []
    if dossier.profile:
        lines.append(f"Profile: {dossier.profile}")
    if dossier.suggested_animal:
        lines.append(f"Suggested animal: {dossier.suggested_animal}")
    lines.append("Interview:")
    for index, question in enumerate(dossier.questions, start=1):
        lines.append(f"  Question {index}: {question}")
        answer_index = index - 1
        if answer_index < len(dossier.answers):
            lines.append(f"  Answer {index}: {dossier.answers[answer_index]}")
    return "\n".join(lines)


class Converter:
    """Fuses a photo with a dossier into a hybrid portrait, advancing CONVERTING → SCRIPTING."""

    def __init__(self, state: StateDriver, client: ConverterClient) -> None:
        self._state = state
        self._client = client

    @log_call
    def convert(self, chat_id: int) -> ConverterOutput:
        """Run the conversion for a chat, advancing phase on success."""
        session = self._state.load(chat_id)
        if session.phase is not Phase.CONVERTING:
            raise ConverterError(f"chat {chat_id} is not in CONVERTING phase: {session.phase}")

        if session.photo is None:
            raise ConverterError(f"chat {chat_id} has no photo in session")

        if not session.dossier.suggested_animal:
            raise ConverterError(f"chat {chat_id} has no completed dossier")

        image = session.photo
        context = dossier_context(session.dossier)

        raw = self._client.convert(image, context)
        output = parse_output(raw)

        # On success: persist hybrid image reference and advance phase
        session.dossier.profile = (
            (session.dossier.profile or "")
            + f"\n[Hybrid portrait generated: {output.reason or 'success'}]"
        )
        session.phase = Phase.SCRIPTING
        self._state.save(session)

        return output