"""The Converter: fuses the original photo and dossier into a hybrid portrait (Phase 4).

The first pipeline stage to use ``gemini-3.1-flash-image`` — the Bouncer,
Interviewer, and Scripter use ``gemini-3.1-flash-lite``, the Narrator uses
``gemini-3.1-flash-tts-preview``. Its job: read the photo and dossier, generate a
hybrid animal portrait, and deliver it directly to the Telegram chat.

Its answer is a typed contract (requirements decision 2): the model's structured
output is parsed into ``ConverterOutput`` and free text is never interpreted
downstream. Logging is decorator-based via ``log_call`` (decision 9) — no log
statements in the business logic.
"""

from __future__ import annotations

import base64
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from pydantic.annotated_handlers import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from telegram_documentaries.client import TelegramClient
from telegram_documentaries.logutil import log_call, logger
from telegram_documentaries.state import Dossier, Phase, SessionState, StateDriver

#: Sent when the Converter fails to produce a hybrid portrait. In-character,
#: cheeky, and explicit that the documentary continues without the portrait.
CONVERTER_FAILURE_TEXT = (
    "The darkroom spirits were uncooperative today — no hybrid portrait emerged. "
    "But fear not! The narration and voice note will still find their way to you."
)


class ConverterError(ValueError):
    """The model did not return a valid structured converter payload."""


class ConverterOutput(BaseModel):
    """Typed, structured output from the Converter model. Never free text."""

    model_config = ConfigDict(extra="ignore")

    image_bytes: bytes

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        # The model outputs base64-encoded image bytes
        return super().__get_pydantic_json_schema__(core_schema, handler)

    @field_validator("image_bytes", mode="before")
    @classmethod
    def decode_base64(cls, v: object) -> bytes:
        if isinstance(v, str):
            return base64.b64decode(v)
        return v  # type: ignore[return-value]


class ConverterClient(Protocol):
    """The slice of the Gemini image client the Converter depends on.

    ``generate_image`` returns the model's raw structured output for the edge
    parser; the photo bytes and dossier context travel in the message.
    """

    def generate_image(self, photo_bytes: bytes, dossier_context: str) -> str: ...


#: Instruction handed to the Gemini agent: the wildlife documentary image generator persona.
CONVERTER_INSTRUCTION = (
    "You are creating a hybrid portrait for a nature documentary. Fuse the human "
    "subject's likeness with the animal archetype that best reflects their "
    "personality quirks from the dossier. Create a playful, believable "
    "wildlife-documentary-style image where the human's features merge with the "
    "animal's — e.g., a caffeinated badger with coffee-stained whiskers for a "
    "late-night coder, a meticulous beaver with a tiny clipboard for an "
    "organizer, a night-owl bat with oversized headphones for a night owl. The "
    "style is cinematic, detailed, and slightly humorous — like a BBC Earth frame "
    "with a wink."
)


def parse_output(raw: str) -> ConverterOutput:
    """Parse the model's structured output into a typed converter output.

    Anything that is not a JSON object matching the schema — or an output with
    empty image bytes — is raised as a ``ConverterError``; the public boundary
    (``Converter.generate_and_send``, decorated with ``log_call``) logs it
    loudly rather than silently dropping it.
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

    if not output.image_bytes:
        raise ConverterError(f"image_bytes must not be empty: {output.image_bytes!r}")
    return output


def converter_context(photo_bytes: bytes, dossier: Dossier) -> tuple[bytes, str]:
    """Format the dossier (profile, suggested_animal, Q&A) as text for the model prompt.

    Returns the photo bytes and the formatted dossier context string.
    """
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
    return photo_bytes, "\n".join(lines)


class Converter:
    """Reads the photo and dossier, generates a hybrid portrait, sends it via Telegram.

    Phase machine: CONVERTING --(success)--> SCRIPTING
                     CONVERTING --(failure)--> SCRIPTING (pipeline continues)
    """

    def __init__(
        self, state: StateDriver, client: ConverterClient, telegram: TelegramClient
    ) -> None:
        self._state = state
        self._client = client
        self._telegram = telegram

    @log_call
    def generate_and_send(self, chat_id: int) -> ConverterOutput | None:
        """Run the Converter for a chat, advancing phase on success or failure.

        On success: send the hybrid image via Telegram, advance phase to SCRIPTING.
        On failure: log loudly, send CONVERTER_FAILURE_TEXT, advance phase to SCRIPTING
        (pipeline continues per Narrator spec amendment).
        """
        session = self._state.load(chat_id)
        if session.phase is not Phase.CONVERTING:
            self._handle_failure(
                chat_id, session, f"chat {chat_id} is not in CONVERTING phase: {session.phase}"
            )
            return None

        if not session.photo:
            self._handle_failure(
                chat_id, session, f"chat {chat_id} has no photo in CONVERTING phase"
            )
            return None

        if not session.dossier.profile or not session.dossier.suggested_animal:
            self._handle_failure(
                chat_id,
                session,
                f"chat {chat_id} has no completed dossier in CONVERTING phase",
            )
            return None

        try:
            photo_bytes, dossier_context = converter_context(session.photo, session.dossier)
            raw = self._client.generate_image(photo_bytes, dossier_context)
            output = parse_output(raw)
        except Exception as exc:
            self._handle_failure(chat_id, session, str(exc))
            return None

        # On success: send the image and advance the phase. Nothing is mutated
        # until the output has parsed, so a failure leaves CONVERTING intact
        # for the failure path (which still advances to SCRIPTING).
        try:
            self._telegram.send_photo(chat_id, output.image_bytes)
        except Exception as exc:
            self._handle_failure(chat_id, session, f"failed to send photo: {exc}")
            return None

        session.phase = Phase.SCRIPTING
        self._state.save(session)
        return output

    def _handle_failure(self, chat_id: int, session: SessionState, reason: str) -> None:
        """Handle a converter failure: send failure text, advance to SCRIPTING, save."""
        logger.error("converter failed for chat %s: %s", chat_id, reason)
        try:
            self._telegram.send_message(chat_id, CONVERTER_FAILURE_TEXT)
        except Exception:
            # If we can't even send the failure message, the error is already logged
            pass
        session.phase = Phase.SCRIPTING
        self._state.save(session)
