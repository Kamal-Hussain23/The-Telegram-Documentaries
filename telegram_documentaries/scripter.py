"""The Scripter: turns the completed dossier into one paragraph of narration (Phase 5).

The stage runs on ``gemini-3.1-flash-lite`` — the same model as the Bouncer and
the Interviewer. Its answer is a typed contract (requirements decision 3): the
model's structured output is parsed into ``ScripterOutput`` and free text is
never interpreted downstream. The output is code-enforced to be a single
paragraph of at most 90 words with no markdown (decision 4), ready for the
Narrator (Phase 6) to send straight to voice synthesis. Logging is decorator
based via ``log_call`` (decision 9) — no log statements in the business logic.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from telegram_documentaries.logutil import log_call
from telegram_documentaries.state import Dossier, Phase, StateDriver

#: Hard upper bound on the narration paragraph (decision 4, split on
#: whitespace). The Narrator (Phase 6) expects a short, voice-ready script.
MAX_SCRIPT_WORDS = 90

#: Regexes matching real markdown *constructs* — bold, italic, headings, code,
#: strikethrough, links/images. Ordinary prose punctuation is deliberately
#: accepted: a single ``~`` ("~90 words"), plain ``( )`` / ``[ ]``, apostrophes,
#: hyphens, ellipses, and decimals are all fine; only actual formatting is a
#: contract violation (plan 1.2).
MARKDOWN_PATTERNS = (
    re.compile(r"\*\*[^*]+\*\*"),  # bold
    re.compile(r"\*[^*\n]+\*"),  # italic
    re.compile(r"__[^_]+__"),  # bold
    re.compile(r"_[^_\n]+_"),  # italic
    re.compile(r"(?m)^\s{0,3}#{1,6}\s"),  # heading (line start, 1-6 hashes)
    re.compile(r"`+"),  # inline or fenced code
    re.compile(r"~~[^~]+~~"),  # strikethrough
    re.compile(r"!?\[[^\]]*\]\([^)]*\)"),  # link or image
)


def has_markdown(text: str) -> bool:
    """True when ``text`` contains a markdown construct (not mere prose punctuation)."""
    return any(pattern.search(text) for pattern in MARKDOWN_PATTERNS)


#: Sent when the Scripter fails to produce a valid script. In-character (Brian
#: Cox eccentricity), explicit that the dossier is safe, and pointing the user
#: at the retry path: replying with any text re-runs the Scripter. Sending
#: another photo would reset the conversation instead, so the message never
#: suggests it.
SCRIPTING_FAILURE_TEXT = (
    "Ah — a momentary disturbance in the cosmic microwave background; the "
    "narration refused to coalesce. Fear not, the dossier is perfectly safe — "
    "simply reply with anything and I'll try again."
)

#: Instruction handed to the Gemini agent (plan 2.3): the Brian Cox physicist
#: persona. The dossier context travels in the per-call message.
SCRIPTER_INSTRUCTION = (
    "You are Brian Cox, the wonder-struck physicist narrating a nature "
    "documentary about a human subject. Frame the subject's everyday quirks, "
    "bedtime habits, and snacking patterns as the remarkable animal behaviours "
    "of an exotic creature, finding cosmic wonder and poetic scale in the most "
    "mundane of human rituals — 'In the vast kitchen of the universe, the "
    "subject prepares a midnight toast...'. Be intellectually amused, warm, "
    "and a little awed. Return exactly one paragraph of narration of at most "
    "90 words, as plain spoken text with no markdown formatting, ready for "
    "voice synthesis. English only."
)


class ScripterError(ValueError):
    """The model did not return a valid structured scripter output."""


class ScripterOutput(BaseModel):
    """Typed, structured output from the Scripter model. Never free text."""

    model_config = ConfigDict(extra="ignore")

    script: str


class ScripterClient(Protocol):
    """The slice of the Gemini script client the Scripter depends on.

    ``generate_script`` returns the model's raw structured output for the edge
    parser; the dossier context travels in the prompt.
    """

    def generate_script(self, dossier_context: str) -> str: ...


def parse_output(raw: str) -> ScripterOutput:
    """Parse the model's structured output into a typed scripter output.

    Anything that is not a JSON object matching the schema — or a script that
    breaks the output contract (multi-paragraph, over 90 words, markdown) — is
    raised as a ``ScripterError``; the public boundary (``Scripter.generate``,
    decorated with ``log_call``) logs it loudly rather than silently dropping
    it.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScripterError(f"output is not valid JSON: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise ScripterError(f"output must be a JSON object: {raw!r}")
    try:
        output = ScripterOutput.model_validate(payload)
    except ValidationError as exc:
        raise ScripterError(f"output does not match schema: {raw!r}") from exc

    script = output.script
    if not script.strip():
        raise ScripterError(f"script must not be empty: {script!r}")
    # Normalise the many spellings of a paragraph break (Windows CRLF, bare CR,
    # and the unicode paragraph/line separators) down to ``\n`` before checking
    # the single-paragraph contract. A single line break remains a single
    # paragraph; two of them do not.
    normalised = script.replace("\r\n", "\n").replace("\r", "\n")
    normalised = normalised.replace("\u2028", "\n").replace("\u2029", "\n")
    if "\n\n" in normalised:
        raise ScripterError(f"script must be a single paragraph: {script!r}")
    if len(script.split()) > MAX_SCRIPT_WORDS:
        raise ScripterError(
            f"script exceeds {MAX_SCRIPT_WORDS} words ({len(script.split())}): {script!r}"
        )
    if has_markdown(script):
        raise ScripterError(f"script must not contain markdown formatting: {script!r}")
    return output


def dossier_context(dossier: Dossier) -> str:
    """The completed dossier as text, so the model can dramatise it."""
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


class Scripter:
    """Reads the dossier and writes one narration paragraph, advancing SCRIPTING → NARRATING."""

    def __init__(self, state: StateDriver, client: ScripterClient) -> None:
        self._state = state
        self._client = client

    @log_call
    def generate(self, chat_id: int) -> ScripterOutput:
        """Run the Scripter for a chat, advancing phase on success."""
        session = self._state.load(chat_id)
        if session.phase is not Phase.SCRIPTING:
            raise ScripterError(f"chat {chat_id} is not in SCRIPTING phase: {session.phase}")

        if not session.dossier.profile or not session.dossier.suggested_animal:
            raise ScripterError(f"chat {chat_id} has no completed dossier")

        context = dossier_context(session.dossier)
        raw = self._client.generate_script(context)
        output = parse_output(raw)

        # On success: persist the script and advance the phase. Nothing is
        # mutated until the output has parsed, so a failure leaves SCRIPTING
        # intact for a retry.
        session.dossier.script = output.script
        session.phase = Phase.NARRATING
        self._state.save(session)
        return output
