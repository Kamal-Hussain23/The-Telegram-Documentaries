"""The interview flow: one question per turn, budgeted 3–4, then handoff.

Reference: SPECS/2026-10-08-interviewer/plan.md groups 1.3–1.9 and
validation.md acceptance criteria (a)–(e). Everything here runs offline
against the scripted interview client.

Note: ``test_pass_path_replies_with_the_first_question`` supersedes Phase 2's
pass-path placeholder assertion (user-approved pass-path change, plan 5.5);
the Phase 2 test now covers only the unwired-Interviewer fallback, and the
Bouncer's classification and rejection path are untouched.
"""

from __future__ import annotations

import json
import logging

import pytest
from telegram_documentaries.bot import (
    CONVERTING_REPLY,
    ERROR_TEXT,
    INTERVIEWING_PHOTO_REPLY,
    INTERVIEWING_TEXT_REPLY,
    REPLY_TEXT,
    Bot,
)
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import (
    FakeTelegramClient,
    StubInterviewClient,
    StubVisionClient,
    fixture_bytes,
    photo_update,
    profile_json,
    question_json,
    text_update,
)

PERSON = fixture_bytes("person.jpg")
#: A second, visually different fixture. The vision verdict is scripted, so
#: only the bytes matter here — they must differ from ``PERSON``.
OTHER_PERSON = fixture_bytes("landscape.jpg")

Q1 = "What do you do when nobody is watching?"
Q2 = "Describe the strangest thing in your refrigerator."
Q3 = "If your life were a documentary, what would the narrator say?"
Q4 = "Which object in your home are you most protective of?"
FRESH_Q1 = "Right then — fresh start. Who are we filming today?"
PROFILE = (
    "A midnight snacker with a weakness for shiny objects and a "
    "suspiciously organised snack drawer."
)
ANIMAL = "raccoon"


def verdict_json(human_present: bool) -> str:
    return json.dumps({"human_present": human_present})


def three_questions() -> list[str]:
    """The model plays nicely: finishes at the floor of three questions."""
    return [
        question_json(Q1),
        question_json(Q2),
        question_json(Q3, is_final=True),
    ]


def wired_bot(
    client: FakeTelegramClient,
    state: StateDriver,
    stub: StubInterviewClient,
    vision: StubVisionClient,
) -> Bot:
    """A Bot wired to an Interviewer on the shared state driver."""
    return Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, stub),
    )


def make_bot(
    client: FakeTelegramClient,
    stub: StubInterviewClient,
    *,
    verdicts: list[str] | None = None,
) -> tuple[Bot, StateDriver]:
    state = StateDriver()
    vision = StubVisionClient(verdicts if verdicts is not None else [verdict_json(True)])
    return wired_bot(client, state, stub, vision), state


def assert_reset_reply(client: FakeTelegramClient) -> None:
    """The command's single reply invites a fresh portrait rather than echoing
    the placeholder or an interview question."""
    reply = client.sent[-1][1]
    assert reply != REPLY_TEXT
    assert any(word in reply.lower() for word in ("photo", "portrait"))


def client_with_person() -> FakeTelegramClient:
    return FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})


def interview_pending_on_q2(
    client: FakeTelegramClient,
    stub: StubInterviewClient,
    *,
    verdicts: list[str] | None = None,
) -> tuple[Bot, StateDriver]:
    """Photo accepted, one answer given: Q2 is pending and one answer recorded."""
    bot, state = make_bot(client, stub, verdicts=verdicts)
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    return bot, state


# --- start path (plan 1.7) --------------------------------------------------


def test_pass_path_replies_with_the_first_question() -> None:
    client = client_with_person()
    stub = StubInterviewClient(questions=three_questions())
    bot, _ = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    # Exactly one outbound message, and it is question one: the Phase 1
    # placeholder no longer appears on the pass path.
    assert client.sent == [(42, Q1)]
    assert REPLY_TEXT not in [text for _, text in client.sent]


def test_pass_path_starts_the_interview_in_the_session() -> None:
    client = client_with_person()
    stub = StubInterviewClient(questions=three_questions())
    bot, state = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.photo == PERSON
    assert session.dossier.questions == [Q1]
    assert session.dossier.answers == []


def test_second_photo_mid_interview_re_sends_the_pending_question() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, _ = interview_pending_on_q2(
        client, stub, verdicts=[verdict_json(True), verdict_json(True)]
    )

    # Second photo mid-interview now gets mid-interview reply (wrong-payload guard)
    bot.handle_update(photo_update(3, chat_id=42, file_id="other"))

    assert client.sent[-1] == (42, INTERVIEWING_PHOTO_REPLY)
    assert len(client.sent) == 3  # Q1, Q2, and mid-interview reply


def test_second_photo_mid_interview_leaves_the_dossier_and_photo_intact() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = interview_pending_on_q2(
        client, stub, verdicts=[verdict_json(True), verdict_json(True)]
    )

    bot.handle_update(photo_update(3, chat_id=42, file_id="other"))

    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.photo == PERSON  # the original portrait, not the new upload
    assert session.dossier.questions == [Q1, Q2]
    assert session.dossier.answers == ["answer one"]
    assert len(stub.question_calls) == 2  # idempotent: nothing was regenerated.


# --- turn taking and resume (plan 1.4) --------------------------------------


def test_each_inbound_answer_yields_exactly_one_next_question() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    assert client.sent == [(42, Q1)]

    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    assert client.sent == [(42, Q1), (42, Q2)]

    bot.handle_update(text_update(3, chat_id=42, text="answer two"))
    assert client.sent == [(42, Q1), (42, Q2), (42, Q3)]

    session = state.load(42)
    assert session.dossier.questions == [Q1, Q2, Q3]
    assert session.dossier.answers == ["answer one", "answer two"]


def test_the_answer_is_persisted_before_the_next_question_is_generated() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = make_bot(client, stub)
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    bot.handle_update(text_update(2, chat_id=42, text="answer one"))

    session = state.load(42)
    assert session.dossier.answers == ["answer one"]
    # Question two was generated with the answer already in its context.
    assert "answer one" in stub.question_calls[1]


def test_interview_resumes_from_the_driver_across_separate_messages() -> None:
    """Every message is a separate ``handle_update`` on a fresh Bot, so all
    progress must come back from the shared state driver."""
    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )

    def fresh_bot() -> Bot:
        return wired_bot(client, state, stub, vision)

    fresh_bot().handle_update(photo_update(1, chat_id=42, file_id="person"))
    assert client.sent == [(42, Q1)]

    fresh_bot().handle_update(text_update(2, chat_id=42, text="answer one"))
    assert client.sent[-1] == (42, Q2)

    fresh_bot().handle_update(text_update(3, chat_id=42, text="answer two"))
    assert client.sent[-1] == (42, Q3)

    fresh_bot().handle_update(text_update(4, chat_id=42, text="answer three"))
    assert client.sent[-1][0] == 42
    assert ANIMAL in client.sent[-1][1]

    session = state.load(42)
    assert session.phase is Phase.CONVERTING
    assert session.dossier.questions == [Q1, Q2, Q3]
    assert session.dossier.answers == ["answer one", "answer two", "answer three"]


def test_a_whitespace_only_message_is_recorded_like_any_other_answer() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = make_bot(client, stub)
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    bot.handle_update(text_update(2, chat_id=42, text="   "))

    assert client.sent[-1] == (42, Q2)
    assert state.load(42).dossier.answers == ["   "]


def test_non_text_message_mid_interview_keeps_the_default_reply() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = interview_pending_on_q2(client, stub)

    bot.handle_update(text_update(3, chat_id=42, text=None))

    assert client.sent[-1] == (42, INTERVIEWING_TEXT_REPLY)
    session = state.load(42)
    assert session.dossier.questions == [Q1, Q2]
    assert session.dossier.answers == ["answer one"]  # the sticker recorded no answer.
    assert len(stub.question_calls) == 2  # no new question was generated.


# --- completion and handoff (plan 1.5) --------------------------------------


def test_final_answer_persists_the_profile_and_reaches_converting() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    bot.handle_update(text_update(3, chat_id=42, text="answer two"))
    bot.handle_update(text_update(4, chat_id=42, text="answer three"))

    session = state.load(42)
    assert session.phase is Phase.CONVERTING
    assert session.dossier.profile == PROFILE
    assert session.dossier.suggested_animal == ANIMAL
    # Budget floor: exactly three questions, no fourth generation call.
    assert len(stub.question_calls) == 3
    assert len(stub.profile_calls) == 1
    # The synthesis sees the whole accumulated interview, final answer included.
    for answer in ("answer one", "answer two", "answer three"):
        assert answer in stub.profile_calls[0]


def test_completion_reply_reveals_the_animal_but_never_the_full_profile() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, _ = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    bot.handle_update(text_update(3, chat_id=42, text="answer two"))
    bot.handle_update(text_update(4, chat_id=42, text="answer three"))

    assert len(client.sent) == 4  # three questions plus one reveal.
    reply = client.sent[-1][1]
    assert client.sent[-1][0] == 42
    assert ANIMAL in reply
    assert PROFILE not in reply
    assert reply != REPLY_TEXT


def test_text_after_completion_leaves_the_finished_dossier_alone() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = make_bot(client, stub)
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    bot.handle_update(text_update(3, chat_id=42, text="answer two"))
    bot.handle_update(text_update(4, chat_id=42, text="answer three"))
    sent = list(client.sent)

    bot.handle_update(text_update(5, chat_id=42, text="one more question?"))

    # No re-asking, no double synthesis: the completed dossier is untouched.
    # Text in CONVERTING phase gets developing reply (wrong-payload guard).
    assert client.sent == [*sent, (42, CONVERTING_REPLY)]
    assert len(stub.question_calls) == 3
    assert len(stub.profile_calls) == 1
    session = state.load(42)
    assert session.phase is Phase.CONVERTING
    assert session.dossier.profile == PROFILE
    assert session.dossier.suggested_animal == ANIMAL


# --- budget: floor 3 and ceiling 4 are code-enforced (plan 1.3) --------------


def test_model_cannot_end_the_interview_at_question_one() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=[
            question_json(Q1, is_final=True),
            question_json(Q2),
            question_json(Q3, is_final=True),
        ],
        profiles=[profile_json(PROFILE, ANIMAL)],
    )
    bot, state = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))

    assert client.sent[-1] == (42, Q2)  # the hostile is_final was overridden.
    assert len(client.sent) == 2
    assert len(stub.question_calls) == 2
    assert len(stub.profile_calls) == 0
    assert state.load(42).phase is Phase.INTERVIEWING


def test_model_cannot_end_the_interview_at_question_two() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=[
            question_json(Q1),
            question_json(Q2, is_final=True),
            question_json(Q3, is_final=True),
        ],
        profiles=[profile_json(PROFILE, ANIMAL)],
    )
    bot, state = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    bot.handle_update(text_update(3, chat_id=42, text="answer two"))

    assert client.sent[-1] == (42, Q3)  # floor of three holds despite is_final.
    assert len(client.sent) == 3
    assert len(stub.question_calls) == 3
    assert len(stub.profile_calls) == 0
    assert state.load(42).phase is Phase.INTERVIEWING


def test_over_curious_model_is_stopped_at_question_four() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=[
            question_json(Q1),
            question_json(Q2),
            question_json(Q3),
            question_json(Q4),
        ],
        profiles=[profile_json(PROFILE, ANIMAL)],
    )
    bot, state = make_bot(client, stub)

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    bot.handle_update(text_update(3, chat_id=42, text="answer two"))
    bot.handle_update(text_update(4, chat_id=42, text="answer three"))
    assert client.sent[-1] == (42, Q4)
    assert len(stub.question_calls) == 4

    bot.handle_update(text_update(5, chat_id=42, text="answer four"))

    # Ceiling: no fifth question can be generated — straight to synthesis.
    assert len(stub.question_calls) == 4
    assert len(stub.profile_calls) == 1
    assert client.sent[-1][0] == 42
    assert ANIMAL in client.sent[-1][1]
    assert len(client.sent) == 5  # four questions plus one reveal.
    session = state.load(42)
    assert session.phase is Phase.CONVERTING
    assert session.dossier.profile == PROFILE


# --- reset: /start and /restart (plan 1.6) ----------------------------------


@pytest.mark.parametrize("command", ["/start", "/restart"])
def test_command_mid_interview_purges_the_dossier_and_photo(command: str) -> None:
    client = client_with_person()
    stub = StubInterviewClient(questions=[question_json(Q1), question_json(Q2)])
    bot, state = interview_pending_on_q2(client, stub)

    bot.handle_update(text_update(3, chat_id=42, text=command))

    assert len(client.sent) == 3  # Q1, Q2, and exactly one reset reply.
    assert_reset_reply(client)
    session = state.load(42)
    assert session.phase is Phase.AWAITING_PHOTO
    assert session.photo is None
    assert session.dossier.questions == []
    assert session.dossier.answers == []
    assert session.dossier.profile is None
    assert session.dossier.suggested_animal is None


@pytest.mark.parametrize("command", ["/start", "/restart"])
def test_a_photo_after_the_command_starts_a_fresh_interview(command: str) -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=[question_json(Q1), question_json(Q2), question_json(FRESH_Q1)]
    )
    bot, state = interview_pending_on_q2(
        client, stub, verdicts=[verdict_json(True), verdict_json(True)]
    )
    bot.handle_update(text_update(3, chat_id=42, text=command))

    bot.handle_update(photo_update(4, chat_id=42, file_id="person"))

    assert client.sent[-1] == (42, FRESH_Q1)
    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.dossier.questions == [FRESH_Q1]
    assert session.dossier.answers == []  # nothing from the old interview.


def test_command_matches_with_the_bot_name_suffix() -> None:
    client = client_with_person()
    stub = StubInterviewClient(questions=[question_json(Q1), question_json(Q2)])
    bot, state = interview_pending_on_q2(client, stub)

    bot.handle_update(text_update(3, chat_id=42, text="/start@DocumentaryBot"))

    assert len(client.sent) == 3
    assert_reset_reply(client)
    session = state.load(42)
    assert session.phase is Phase.AWAITING_PHOTO
    assert session.photo is None
    assert session.dossier.questions == []


def test_similar_text_is_not_treated_as_a_command() -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=[question_json(Q1), question_json(Q2), question_json(Q3, is_final=True)]
    )
    bot, state = interview_pending_on_q2(client, stub)

    bot.handle_update(text_update(3, chat_id=42, text="/started"))

    assert client.sent[-1] == (42, Q3)  # answered, not reset.
    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.dossier.answers == ["answer one", "/started"]


# --- cross-chat isolation (plan 1.8) ----------------------------------------


def test_two_chats_do_not_share_a_dossier_or_a_photo() -> None:
    client = FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})
    stub = StubInterviewClient(
        questions=[
            question_json(Q1),
            question_json(FRESH_Q1),
            question_json(Q2),
            question_json(Q3),
        ]
    )
    bot, state = make_bot(client, stub, verdicts=[verdict_json(True), verdict_json(True)])

    bot.handle_update(photo_update(1, chat_id=1, file_id="person"))
    bot.handle_update(photo_update(2, chat_id=2, file_id="other"))
    bot.handle_update(text_update(3, chat_id=1, text="chat one answer"))
    bot.handle_update(text_update(4, chat_id=2, text="chat two answer"))

    chat_one = state.load(1)
    chat_two = state.load(2)
    assert chat_one.dossier.questions == [Q1, Q2]
    assert chat_one.dossier.answers == ["chat one answer"]
    assert chat_two.dossier.questions == [FRESH_Q1, Q3]
    assert chat_two.dossier.answers == ["chat two answer"]
    assert chat_one.photo == PERSON
    assert chat_two.photo == OTHER_PERSON
    assert chat_one.photo != chat_two.photo


def test_each_chat_is_revealed_its_own_animal_not_the_other_s() -> None:
    profile_one = "A tidy chaos-monkey with a ritualistic tea schedule."
    profile_two = "A grumpy burrower who hoards only the finest cardboard."
    client = FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})
    stub = StubInterviewClient(
        questions=[
            question_json(Q1),  # chat 1, question 1
            question_json(FRESH_Q1),  # chat 2, question 1
            question_json(Q2),  # chat 1, question 2
            question_json(Q3),  # chat 2, question 2
            question_json(Q4, is_final=True),  # chat 1, question 3
            question_json(Q4, is_final=True),  # chat 2, question 3
        ],
        profiles=[profile_json(profile_one, "macaque"), profile_json(profile_two, "badger")],
    )
    bot, state = make_bot(client, stub, verdicts=[verdict_json(True), verdict_json(True)])

    bot.handle_update(photo_update(1, chat_id=1, file_id="person"))
    bot.handle_update(photo_update(2, chat_id=2, file_id="other"))
    bot.handle_update(text_update(3, chat_id=1, text="chat one answer"))
    bot.handle_update(text_update(4, chat_id=2, text="chat two answer"))
    bot.handle_update(text_update(5, chat_id=1, text="chat one more"))
    bot.handle_update(text_update(6, chat_id=2, text="chat two more"))
    bot.handle_update(text_update(7, chat_id=1, text="chat one final"))
    bot.handle_update(text_update(8, chat_id=2, text="chat two final"))

    reveal_one = client.sent[-2][1]
    reveal_two = client.sent[-1][1]
    assert client.sent[-2][0] == 1
    assert client.sent[-1][0] == 2
    assert "macaque" in reveal_one and "badger" not in reveal_one
    assert "badger" in reveal_two and "macaque" not in reveal_two

    chat_one = state.load(1)
    chat_two = state.load(2)
    assert chat_one.phase is Phase.CONVERTING
    assert chat_two.phase is Phase.CONVERTING
    assert chat_one.dossier.profile == profile_one
    assert chat_one.dossier.suggested_animal == "macaque"
    assert chat_two.dossier.profile == profile_two
    assert chat_two.dossier.suggested_animal == "badger"
    assert "chat two" not in " ".join(chat_one.dossier.answers)
    assert "chat one" not in " ".join(chat_two.dossier.answers)


# --- graceful degradation mid-interview (plan 1.9) --------------------------


def test_gemini_failure_degrades_gracefully_and_stays_resumable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=[
            question_json(Q1),
            question_json(Q2),
            RuntimeError("gemini exploded"),
            question_json(Q3, is_final=True),
        ],
        profiles=[profile_json(PROFILE, ANIMAL)],
    )
    bot, state = make_bot(client, stub)
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))

    with caplog.at_level(logging.ERROR):
        bot.handle_update(text_update(3, chat_id=42, text="answer two"))

    assert client.sent[-1] == (42, ERROR_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.dossier.profile is None
    assert session.dossier.questions == [Q1, Q2]
    assert session.dossier.answers[0] == "answer one"

    # The dossier survived, so the conversation carries on and completes.
    bot.handle_update(text_update(4, chat_id=42, text="answer three"))
    assert client.sent[-1] == (42, Q3)
    bot.handle_update(text_update(5, chat_id=42, text="answer four"))
    assert ANIMAL in client.sent[-1][1]
    assert state.load(42).phase is Phase.CONVERTING
    assert len(stub.profile_calls) == 1


def test_malformed_model_output_degrades_gracefully_and_stays_resumable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = client_with_person()
    stub = StubInterviewClient(
        questions=[
            question_json(Q1),
            question_json(Q2),
            "sure thing — ask them about their childhood!",
            question_json(Q3, is_final=True),
        ],
        profiles=[profile_json(PROFILE, ANIMAL)],
    )
    bot, state = make_bot(client, stub)
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))

    with caplog.at_level(logging.ERROR):
        bot.handle_update(text_update(3, chat_id=42, text="answer two"))

    assert client.sent[-1] == (42, ERROR_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.dossier.profile is None
    assert session.dossier.questions == [Q1, Q2]
    assert session.dossier.answers[0] == "answer one"

    bot.handle_update(text_update(4, chat_id=42, text="answer three"))
    assert client.sent[-1] == (42, Q3)
    bot.handle_update(text_update(5, chat_id=42, text="answer four"))
    assert ANIMAL in client.sent[-1][1]
    assert state.load(42).phase is Phase.CONVERTING
    assert len(stub.profile_calls) == 1


def test_send_failure_during_an_answer_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    class FailingSendClient(FakeTelegramClient):
        def send_message(self, chat_id: int, text: str) -> None:
            raise ConnectionError("cannot send")

    client = FailingSendClient(downloads={"person": PERSON})
    stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot, state = make_bot(client, stub)
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    with caplog.at_level(logging.ERROR):
        bot.handle_update(text_update(2, chat_id=42, text="answer one"))

    assert client.sent == []
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.dossier.questions == [Q1, Q2]  # the turn was not lost.
    assert session.dossier.answers == ["answer one"]
