"""The Bouncer: the vision gate deciding whether a photo contains a human.

The first pipeline stage to talk to Gemini. Its answer is a typed contract
(requirements decision 4): the model's structured verdict is parsed into a
Pydantic model and free text is never interpreted downstream. Logging is
decorator-based (decision 6) — no log statements in the business logic.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from telegram_documentaries.logutil import log_call

#: Sent when the photo contains no discernible human. In-character, cheeky, and
#: explicit that the submission must contain a human.
REJECTION_TEXT = (
    "Whoa there — that's not a documentary subject, that's scenery! "
    "My lens only focuses on humans. Send a photo with a discernible human "
    "face or body and we'll roll camera."
)

#: Instruction handed to the Gemini agent; the model reports the verdict via the
#: structured `BouncerVerdict` output schema.
BOUNCER_INSTRUCTION = (
    "You are The Bouncer, the vision gate of a wildlife-documentary bot. "
    "Look at the supplied image and decide whether it contains a discernible "
    "human face or body. Report your decision as the structured verdict."
)


class VerdictError(ValueError):
    """The model did not return a valid structured verdict."""


class BouncerVerdict(BaseModel):
    """Typed, structured answer from the Bouncer. Never free text."""

    model_config = ConfigDict(extra="ignore")

    human_present: bool
    confidence: float | None = None
    reason: str | None = None


class VisionClient(Protocol):
    """The slice of the Gemini vision client the Bouncer depends on."""

    def classify(self, image: bytes) -> str: ...


def parse_verdict(raw: str) -> BouncerVerdict:
    """Parse the model's structured output into a typed verdict.

    Anything that is not a JSON object matching the schema is raised as a
    ``VerdictError``; the public boundary (``Bouncer.classify``, decorated with
    ``log_call``) logs it loudly rather than silently dropping it.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerdictError(f"verdict is not valid JSON: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise VerdictError(f"verdict must be a JSON object: {raw!r}")
    try:
        return BouncerVerdict.model_validate(payload)
    except ValidationError as exc:
        raise VerdictError(f"verdict does not match schema: {raw!r}") from exc


class Bouncer:
    """Classifies an image as human-present or not, returning a typed verdict."""

    def __init__(self, vision: VisionClient) -> None:
        self._vision = vision

    @log_call
    def classify(self, image: bytes) -> BouncerVerdict:
        return parse_verdict(self._vision.classify(image))
