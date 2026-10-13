"""The Interviewer: the orchestrator running the stateful Q&A (Phase 3).

TECH.md's orchestrator stage. It owns the conversation loop — one question per
turn, 3–4 in total — accumulates the dossier in session state, synthesises it
into a profile plus a suggested animal on the final answer, and hands the
pipeline on by advancing ``INTERVIEWING → CONVERTING`` through the single
shared ``StateDriver``.

Its two model outputs are typed contracts (requirements decision 2): raw
structured output is parsed at the edge into ``NextQuestion`` /
``InterviewProfile`` and anything else is a handled ``InterviewerError``.
Logging is decorator-based via ``log_call`` (decision 9) — no log statements
in the business logic.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from telegram_documentaries.logutil import log_call
from telegram_documentaries.state import Dossier, Phase, SessionState, StateDriver

#: Question budget. Both bounds are hard and code-enforced (decision 3): the
#: floor protects against a terse model, the ceiling against an over-curious
#: one. There is deliberately no config knob for these (YAGNI).
MIN_QUESTIONS = 3
MAX_QUESTIONS = 4

#: Instruction handed to the Gemini agent (plan 3.7): the persona only — the
#: per-call task and the accumulated Q&A travel in the prompt.
INTERVIEW_INSTRUCTION = (
    "You are The Interviewer, the field correspondent of a wildlife-documentary "
    "bot. Interview the subject one question at a time: investigative, playful "
    "and slightly eccentric, adapting each question to the answers already "
    "given. Keep it to a short interview of 3-4 questions, then distil the "
    "answers into a concise behavioural profile and the single animal the "
    "subject most resembles. English only."
)


class InterviewerError(ValueError):
    """The model did not return a valid structured interview payload."""


class NextQuestion(BaseModel):
    """Typed, structured next question from the model. Never free text."""

    model_config = ConfigDict(extra="ignore")

    question: str
    #: Whether the interview finishes once this question is answered. The code
    #: decides when that flag may be honoured (the budget floor/ceiling).
    is_final: bool


class InterviewProfile(BaseModel):
    """Typed, structured dossier synthesis: the handoff to the next stage."""

    model_config = ConfigDict(extra="ignore")

    profile: str
    suggested_animal: str


class InterviewClient(Protocol):
    """The slice of the Gemini interview client the Interviewer depends on.

    Both methods return the model's raw structured output for the edge parsers;
    ``context`` carries the accumulated Q&A so the model adapts to it (plan 4.2).
    """

    def generate_question(self, context: str) -> str: ...

    def synthesize_profile(self, context: str) -> str: ...


def parse_next_question(raw: str) -> NextQuestion:
    """Parse the model's structured output into a typed next question.

    Anything that is not a JSON object matching the schema is raised as an
    ``InterviewerError``; the public boundary (``Interviewer.start`` /
    ``Interviewer.answer``, decorated with ``log_call``) logs it loudly rather
    than silently dropping it.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InterviewerError(f"next question is not valid JSON: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise InterviewerError(f"next question must be a JSON object: {raw!r}")
    try:
        return NextQuestion.model_validate(payload)
    except ValidationError as exc:
        raise InterviewerError(f"next question does not match schema: {raw!r}") from exc


def parse_profile(raw: str) -> InterviewProfile:
    """Parse the model's structured output into a typed profile handoff."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InterviewerError(f"profile is not valid JSON: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise InterviewerError(f"profile must be a JSON object: {raw!r}")
    try:
        return InterviewProfile.model_validate(payload)
    except ValidationError as exc:
        raise InterviewerError(f"profile does not match schema: {raw!r}") from exc


def dossier_context(dossier: Dossier) -> str:
    """The accumulated Q&A as text, so the model can adapt to prior answers."""
    lines: list[str] = []
    for index, question in enumerate(dossier.questions, start=1):
        lines.append(f"Question {index}: {question}")
        answer_index = index - 1
        if answer_index < len(dossier.answers):
            lines.append(f"Answer {index}: {dossier.answers[answer_index]}")
    # Any answer recorded beyond its question (a turn that failed mid-flight)
    # still belongs in the record.
    for index, answer in enumerate(dossier.answers[len(dossier.questions) :], start=1):
        lines.append(f"Answer {len(dossier.questions) + index}: {answer}")
    return "\n".join(lines)


def _pending_question(session: SessionState) -> str | None:
    """The asked-but-unanswered question, or None when nothing is pending."""
    dossier = session.dossier
    if len(dossier.questions) > len(dossier.answers):
        return dossier.questions[-1]
    return None


def _reveal_reply(suggested_animal: str) -> str:
    """The in-character completion reply: the animal only, never the profile."""
    return (
        f"Well, that's a wrap on the fieldwork — the subject is a "
        f"{suggested_animal}, through and through. Filing the dossier with "
        f"post-production now."
    )


class Interviewer:
    """Owns the interview turn loop and advances INTERVIEWING → CONVERTING."""

    def __init__(self, state: StateDriver, client: InterviewClient) -> None:
        self._state = state
        self._client = client

    @log_call
    def start(self, chat_id: int, photo: bytes) -> str:
        """Begin the interview, or — idempotently — re-send its pending question.

        A photo arriving mid-interview never clobbers the accumulated dossier
        (decision 7); one arriving once the interview is complete re-sends the
        reveal rather than destroying the handoff the next stage is about to
        read.
        """
        session = self._state.load(chat_id)
        if session.phase is Phase.INTERVIEWING:
            pending = _pending_question(session)
            if pending is not None:
                return pending
            # No question pending: a previous turn failed mid-flight. Carry on
            # from the dossier instead of letting a photo wipe it.
            return self._advance(session)

        session.phase = Phase.INTERVIEWING
        session.photo = photo
        session.dossier = Dossier()
        self._state.save(session)
        return self._advance(session)

    @log_call
    def answer(self, chat_id: int, text: str) -> str:
        """Record one answer and reply with exactly one next step (plan 3.3)."""
        session = self._state.load(chat_id)
        session.dossier.answers.append(text)
        return self._advance(session)

    def _advance(self, session: SessionState) -> str:
        """Record the answer → decide question-or-finish → persist → reply."""
        dossier = session.dossier
        if dossier.awaiting_final or len(dossier.questions) >= MAX_QUESTIONS:
            # The ceiling is reached: no generation call, straight to synthesis.
            return self._complete(session)

        parsed = parse_next_question(self._client.generate_question(dossier_context(dossier)))
        asked = len(dossier.questions)
        next_number = asked + 1
        if next_number >= MAX_QUESTIONS:
            is_final = True  # the fourth question is always final (decision 3)
        elif next_number >= MIN_QUESTIONS:
            is_final = parsed.is_final  # honoured only from question 3 onward
        else:
            is_final = False  # the floor is hard: a terse model cannot shorten it
        dossier.questions.append(parsed.question)
        dossier.awaiting_final = is_final
        self._state.save(session)
        return parsed.question

    def _complete(self, session: SessionState) -> str:
        """Synthesise the dossier, persist the handoff, advance the phase."""
        dossier = session.dossier
        parsed = parse_profile(self._client.synthesize_profile(dossier_context(dossier)))
        dossier.profile = parsed.profile
        dossier.suggested_animal = parsed.suggested_animal
        session.phase = Phase.CONVERTING
        self._state.save(session)
        return _reveal_reply(parsed.suggested_animal)
